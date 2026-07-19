"""Запуск конвейера по YAML/TOML-описанию.

Pipeline-файл — это список шагов::

    steps:
      - op: ingest.file
        params: {path: input.pdf}
        output: doc          # имя переменной в контексте

      - op: extract.text
        input: doc           # откуда взять вход
        output: text

      - op: render.latex
        input: text
        params: {title: My doc}
        output: tex

    output: tex             # итоговое значение
    bib:                    # начальный контекст (опционально)
      - {index: 1, ...}

Каждый шаг — зарегистрированная ``@operation``. Контекст (``ctx``) хранит
промежуточные значения по именам. В конце возвращается ``ctx[output]``.

Поддерживает ``inputs``/``params`` через ``str.format(**ctx)`` — позволяет
передавать между шагами не только значения, но и форматированные строки.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from textalchemy.core.registry import get

try:
    import yaml  # type: ignore[import-not-found]

    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    name: str
    op: str
    value: Any = None
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    steps: list[StepResult] = field(default_factory=list)
    final: Any = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "error": self.error,
            "final": _safe(self.final),
            "steps": [{"name": s.name, "op": s.op, "error": s.error, "warnings": s.warnings} for s in self.steps],
        }


def _safe(v: Any) -> Any:
    """Преобразовать значение в JSON-сериализуемое."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (list, tuple)):
        return [_safe(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _safe(x) for k, x in v.items()}
    if isinstance(v, Path):
        return str(v)
    return str(v)


def _interpolate(value: Any, ctx: dict) -> Any:
    """Если значение — str и содержит ``{name}``, подставить из ``ctx``."""
    if isinstance(value, str) and "{" in value:
        safe_ctx = {k: v for k, v in ctx.items()
                    if isinstance(k, str) and not k.startswith("_")}
        try:
            return value.format(**safe_ctx)
        except (KeyError, IndexError):
            return value
    if isinstance(value, dict):
        return {k: _interpolate(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, ctx) for v in value]
    return value


def _resolve_input(value: Any, ctx: dict) -> Any:
    """Если значение — строка-ссылка на контекст (``$name``), взять из ctx."""
    if isinstance(value, str) and value.startswith("$"):
        return ctx.get(value[1:])
    return value


def load_pipeline(path: Union[str, Path]) -> dict:
    """Загрузить описание pipeline из .yaml/.yml/.toml/.json."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    text = p.read_text(encoding="utf-8-sig")
    suffix = p.suffix.lower()
    if suffix in (".yaml", ".yml"):
        if not _HAS_YAML:
            raise RuntimeError("PyYAML not installed; pip install pyyaml")
        return yaml.safe_load(text) or {}
    if suffix == ".toml":
        return tomllib.loads(text)
    if suffix == ".json":
        import json

        return json.loads(text)
    # по расширению не угадали — пробуем YAML, потом TOML
    if _HAS_YAML:
        try:
            return yaml.safe_load(text) or {}
        except Exception:  # noqa: BLE001
            pass
    return tomllib.loads(text)


def run_pipeline(
    spec: Union[str, Path, dict],
    *,
    initial_ctx: Optional[dict] = None,
) -> RunResult:
    """Выполнить pipeline. ``spec`` — путь к файлу или готовый dict.

    Контекст (``ctx``) копирует ``initial_ctx``, затем накапливает результаты шагов.
    """
    if not isinstance(spec, dict):
        spec = load_pipeline(spec)
    steps = spec.get("steps") or []
    output_name = spec.get("output")

    ctx: dict = dict(initial_ctx or {})
    # Всё, что в spec вне ``steps``/``output`` — это начальный контекст.
    for k, v in spec.items():
        if k in ("steps", "output"):
            continue
        if k not in ctx:
            ctx[k] = v
    result = RunResult()

    for i, step in enumerate(steps):
        op_id = step.get("op")
        name = step.get("output") or f"step{i}"
        sr = StepResult(name=name, op=op_id)
        result.steps.append(sr)

        if not op_id:
            sr.error = "missing 'op'"
            result.error = f"step {i}: {sr.error}"
            return result
        try:
            spec_op = get(op_id)
        except KeyError as e:
            sr.error = str(e)
            result.error = f"step {i}: {sr.error}"
            return result

        params = _interpolate(step.get("params") or {}, ctx)
        input_name = step.get("input")
        if input_name:
            # Подставляем входной параметр операции (имя из spec.input_param).
            params[spec_op.input_param] = ctx.get(input_name)
        else:
            # Если params содержит строку, начинающуюся с $ — это ссылка на ctx.
            for pname, pval in list(params.items()):
                params[pname] = _resolve_input(pval, ctx)

        try:
            value = spec_op.func(**params)
        except Exception as e:  # noqa: BLE001
            sr.error = f"{type(e).__name__}: {e}"
            result.error = f"step {i} ({op_id}) failed: {sr.error}"
            return result
        ctx[name] = value
        sr.value = _safe(value)
        logger.info("step %d: %s -> %s", i, op_id, name)

    if output_name:
        result.final = ctx.get(output_name)
    elif result.steps:
        result.final = ctx.get(result.steps[-1].name)
    return result


__all__ = ["StepResult", "RunResult", "load_pipeline", "run_pipeline"]
