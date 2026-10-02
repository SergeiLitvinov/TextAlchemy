"""Каталог операций и параметров для конструктора конвейера приложения."""
from __future__ import annotations

import inspect
import json
from typing import Any

from textalchemy.core.registry import all_operations
from textalchemy.pipeline import register_builtin_operations


def operation_catalog() -> list[dict[str, Any]]:
    register_builtin_operations()
    result = []
    for op in all_operations():
        params: dict[str, Any] = {}
        try:
            signature = inspect.signature(op.func)
        except (TypeError, ValueError):  # pragma: no cover
            signature = None
        if signature is not None:
            for name, param in signature.parameters.items():
                if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                    continue
                params[name] = {
                    "default": _param_default(param.default),
                    "required": param.default is inspect.Parameter.empty,
                    "annotation": _annotation_name(param.annotation),
                }
        result.append({
            "id": op.id,
            "input_type": op.input_type,
            "output_type": op.output_type,
            "input_param": op.input_param,
            "description": op.description,
            "tags": op.tags,
            "params": params,
        })
    return result


def _param_default(value: Any) -> Any:
    """Превратить значение по умолчанию в JSON-safe (коллекции — как JSON-строка)."""
    if value is inspect.Parameter.empty or value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=False)
    except (TypeError, ValueError):
        return repr(value)


def _annotation_name(annotation: Any) -> str:
    """Упростить аннотацию параметра до строки (Optional[X] -> X)."""
    if annotation is inspect.Parameter.empty:
        return ""
    origin = getattr(annotation, "__origin__", None)
    if origin is not None:
        args = getattr(annotation, "__args__", ())
        if origin is bool:
            return "bool"
        if origin in (list, tuple, set, dict):
            name = getattr(origin, "__name__", str(origin))
            if args:
                inner = ", ".join(_annotation_name(a) for a in args)
                return f"{name}[{inner}]"
            return name
        if origin is None and args:
            return ", ".join(_annotation_name(a) for a in args)
        return getattr(origin, "__name__", str(origin))
    return getattr(annotation, "__name__", str(annotation))
