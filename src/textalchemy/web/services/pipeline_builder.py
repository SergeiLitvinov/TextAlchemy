"""Сценарии конструктора конвейеров, вызываемые без HTTP."""

from __future__ import annotations

import io
import json
from typing import Any

import yaml

from textalchemy.core.registry import get
from textalchemy.pipeline import register_builtin_operations
from textalchemy.web.services.pipeline_files import execute_web_pipeline

_STEP_KEYS = ("steps", "output")


def _parse_spec(spec: str) -> dict[str, Any]:
    try:
        value = json.loads(spec)
    except json.JSONDecodeError:
        try:
            value = yaml.safe_load(spec)
        except yaml.YAMLError as error:
            raise ValueError(f"Некорректный YAML/JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("Pipeline spec должен быть объектом (dict)")
    return value


def _normalize_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Разложить spec на шаги, итоговый output и начальный контекст."""
    steps = []
    for index, step in enumerate(spec.get("steps") or []):
        if not isinstance(step, dict):
            continue
        steps.append(
            {
                "index": index,
                "op": step.get("op", ""),
                "output": step.get("output", ""),
                "input": step.get("input", ""),
                "params": step.get("params") or {},
            }
        )
    ctx = {key: value for key, value in spec.items() if key not in _STEP_KEYS}
    return {"steps": steps, "output": spec.get("output", ""), "ctx": ctx}


def _validate_spec(spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    known = set(key for key in spec if key not in _STEP_KEYS)
    outputs: set[str] = set()
    steps = spec.get("steps") or []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append({"step": index, "message": "шаг должен быть объектом"})
            continue
        op_id = step.get("op")
        if not op_id:
            errors.append({"step": index, "message": "missing 'op'"})
            continue
        try:
            get(op_id)
        except KeyError as error:
            errors.append({"step": index, "message": str(error)})
            continue
        output = step.get("output") or f"step{index}"
        if output in outputs:
            errors.append({"step": index, "message": f"дублируется имя вывода {output!r}"})
        outputs.add(output)
        input_name = step.get("input")
        if input_name and input_name not in known:
            errors.append({"step": index, "message": f"вход {input_name!r} не определён"})
        known.add(output)
    final_output = spec.get("output")
    if final_output and final_output not in known:
        errors.append({"step": None, "message": f"итоговый output {final_output!r} не определён"})
    if not steps:
        warnings.append("В пайплайне нет шагов")
    return errors, warnings


def run_pipeline(spec: str) -> dict[str, Any]:
    register_builtin_operations()
    try:
        pipeline_def = _parse_spec(spec)
    except ValueError as error:
        return {"success": False, "error": str(error)}
    try:
        return execute_web_pipeline(pipeline_def)
    except (ValueError, KeyError, TypeError, OSError) as error:
        return {"success": False, "error": str(error)}


def parse_pipeline(spec: str) -> dict[str, Any]:
    """Разобрать YAML/JSON в нормализованную структуру для визуального конструктора."""
    try:
        pipeline_def = _parse_spec(spec)
    except ValueError as error:
        return {"success": False, "error": str(error)}
    return {"success": True, "spec": _normalize_spec(pipeline_def)}


def pipeline_yaml(spec: str) -> dict[str, Any]:
    """Сериализовать (JSON или YAML) spec в канонический YAML для экспертного режима."""
    try:
        pipeline_def = _parse_spec(spec)
    except ValueError as error:
        return {"success": False, "error": str(error)}
    buffer = io.StringIO()
    yaml.safe_dump(pipeline_def, buffer, allow_unicode=True, sort_keys=False)
    return {"success": True, "yaml": buffer.getvalue()}


def validate_pipeline(spec: str) -> dict[str, Any]:
    """Проверить связи шагов без выполнения пайплайна."""
    register_builtin_operations()
    try:
        pipeline_def = _parse_spec(spec)
    except ValueError as error:
        return {"success": False, "errors": [{"step": None, "message": str(error)}], "warnings": []}
    errors, warnings = _validate_spec(pipeline_def)
    return {"success": not errors, "errors": errors, "warnings": warnings}
