"""Application file loaders and compatible validation for template schemas."""

import json
import tomllib
from pathlib import Path
from typing import Any

from textalchemy.core.exceptions import GenerateError
from textalchemy.templating import (
    TemplateError,
    TemplateField,
    TemplateSchema,
    TemplateValueType,
)
from textalchemy.templating import (
    validate_template_data as _validate,
)
from textalchemy.templating.schema import _get_path as _get_path
from textalchemy.templating.schema import _set_path as _set_value


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    try:
        _set_value(data, path, value)
    except TemplateError as error:
        raise GenerateError(str(error)) from error


def validate_template_data(schema: TemplateSchema | dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Validate using the template engine and preserve application errors."""
    try:
        return _validate(schema, data)
    except TemplateError as error:
        raise GenerateError(str(error)) from error


def load_template_schema(path: str | Path) -> TemplateSchema:
    """Загрузить схему шаблона из JSON, YAML или TOML."""

    return TemplateSchema.from_dict(load_template_data(path))


def load_template_data(path: str | Path) -> dict[str, Any]:
    """Загрузить объект данных из JSON, YAML или TOML."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    text = source.read_text(encoding="utf-8")
    suffix = source.suffix.lower()
    if suffix == ".json":
        value = json.loads(text)
    elif suffix == ".toml":
        value = tomllib.loads(text)
    elif suffix in {".yaml", ".yml"}:
        import yaml

        value = yaml.safe_load(text)
    else:
        raise GenerateError(f"Unsupported template data format: {suffix or '<none>'}")
    if not isinstance(value, dict):
        raise GenerateError(f"Template data must be an object: {source}")
    return value


__all__ = [
    "TemplateField",
    "TemplateSchema",
    "TemplateValueType",
    "load_template_data",
    "load_template_schema",
    "validate_template_data",
]
