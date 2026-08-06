"""Реестр операций конвейера.

Каждая операция — функция, обёрнутая декоратором ``@operation("id")``.
Реестр нужен для трёх вещей:

1. CLI-команда ``textalchemy run pipeline.toml`` собирает пайплайн по имени.
2. Web UI показывает доступные операции.
3. Тесты могут перебрать все операции и проверить контракт.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class OperationSpec:
    """Описание операции для CLI/web."""

    id: str
    func: Callable[..., Any]
    input_type: Optional[str] = None
    output_type: Optional[str] = None
    input_param: str = "input"
    description: str = ""
    tags: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


_REGISTRY: dict[str, OperationSpec] = {}

#: Маркер, которым декоратор помечает функцию операции; переживает ``reset()``.
_SPEC_MARKER = "__textalchemy_operation_spec__"


def operation(
    op_id: str,
    *,
    input_type: Optional[str] = None,
    output_type: Optional[str] = None,
    input_param: str = "input",
    description: str = "",
    tags: Optional[list[str]] = None,
    **defaults: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Декоратор регистрации операции.

    Использование::

        @operation("ingest.file", input_type="path", output_type="Document",
                   description="Открыть файл и собрать Document")
        def ingest_file(path: str | Path) -> Document: ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        doc = (func.__doc__ or "").strip()
        spec = OperationSpec(
            id=op_id,
            func=func,
            input_type=input_type,
            output_type=output_type,
            input_param=input_param,
            description=description or (doc.splitlines()[0] if doc else ""),
            tags=list(tags or []),
            params=dict(defaults),
        )
        register(spec)
        setattr(func, _SPEC_MARKER, spec)
        return func

    return decorator


def register(spec: OperationSpec) -> None:
    """Явно зарегистрировать готовый ``OperationSpec``; дубликаты запрещены."""
    if spec.id in _REGISTRY:
        raise ValueError(f"Operation id {spec.id!r} already registered")
    _REGISTRY[spec.id] = spec


def re_register(spec: OperationSpec) -> None:
    """Зарегистрировать spec, если его ещё нет (не перезаписывая существующий)."""
    if spec.id not in _REGISTRY:
        _REGISTRY[spec.id] = spec


def spec_for(func: Callable[..., Any]) -> Optional[OperationSpec]:
    """Вернуть spec, которым ``@operation`` пометил функцию (или ``None``)."""
    return getattr(func, _SPEC_MARKER, None)


def get(op_id: str) -> OperationSpec:
    if op_id not in _REGISTRY:
        raise KeyError(f"Unknown operation: {op_id!r}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[op_id]


def all_operations() -> list[OperationSpec]:
    return list(_REGISTRY.values())


def by_tag(tag: str) -> list[OperationSpec]:
    return [s for s in _REGISTRY.values() if tag in s.tags]


def reset() -> None:
    """Сброс реестра. Только для тестов."""
    _REGISTRY.clear()


@contextmanager
def isolated() -> Iterator[None]:
    """Контекст для изоляции реестра в тестах: сбрасывает до, восстанавливает после."""
    snapshot = dict(_REGISTRY)
    _REGISTRY.clear()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(snapshot)


__all__ = [
    "operation",
    "OperationSpec",
    "register",
    "re_register",
    "spec_for",
    "get",
    "all_operations",
    "by_tag",
    "reset",
    "isolated",
]
