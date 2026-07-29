"""Типизированная схема входных данных шаблона."""

from __future__ import annotations

import copy
import json
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from textalchemy.core.exceptions import GenerateError

_MISSING = object()


class TemplateValueType(str, Enum):
    ANY = "any"
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    IMAGE = "image"
    FORMULA = "formula"


@dataclass(frozen=True)
class TemplateField:
    name: str
    type: TemplateValueType = TemplateValueType.ANY
    required: bool = True
    default: Any = field(default=_MISSING, repr=False)
    description: str = ""

    @property
    def has_default(self) -> bool:
        return self.default is not _MISSING


@dataclass
class TemplateSchema:
    fields: list[TemplateField] = field(default_factory=list)
    allow_extra: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TemplateSchema:
        raw_fields = value.get("fields", [])
        fields: list[TemplateField] = []
        if isinstance(raw_fields, dict):
            raw_fields = [{"name": name, **options} for name, options in raw_fields.items()]
        for raw in raw_fields:
            kwargs: dict[str, Any] = {
                "name": raw["name"],
                "type": TemplateValueType(raw.get("type", TemplateValueType.ANY.value)),
                "required": raw.get("required", True),
                "description": raw.get("description", ""),
            }
            if "default" in raw:
                kwargs["default"] = raw["default"]
            fields.append(TemplateField(**kwargs))
        return cls(fields=fields, allow_extra=value.get("allow_extra", True))

    def to_dict(self) -> dict[str, Any]:
        fields = []
        for item in self.fields:
            raw = {
                "name": item.name,
                "type": item.type.value,
                "required": item.required,
                "description": item.description,
            }
            if item.has_default:
                raw["default"] = item.default
            fields.append(raw)
        return {"fields": fields, "allow_extra": self.allow_extra}


def validate_template_data(schema: TemplateSchema | dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Проверить данные, применить defaults и вернуть независимую копию."""

    from textalchemy.generate.model_template import TemplateFormula, TemplateImage

    if isinstance(schema, dict):
        schema = TemplateSchema.from_dict(schema)
    result = copy.deepcopy(data)
    errors: list[str] = []
    field_names = {item.name for item in schema.fields}
    for item in schema.fields:
        exists, value = _get_path(result, item.name)
        if not exists:
            if item.has_default:
                _set_path(result, item.name, copy.deepcopy(item.default))
            elif item.required:
                errors.append(f"{item.name}: required value is missing")
            continue
        try:
            value = _coerce_typed_value(value, item.type, TemplateImage, TemplateFormula)
            _set_path(result, item.name, value)
        except (TypeError, ValueError) as error:
            errors.append(f"{item.name}: {error}")
            continue
        if not _matches_type(value, item.type, TemplateImage, TemplateFormula):
            errors.append(f"{item.name}: expected {item.type.value}, got {type(value).__name__}")
    if not schema.allow_extra:
        declared_roots = {name.split(".", 1)[0] for name in field_names}
        for name in sorted(set(result) - declared_roots):
            errors.append(f"{name}: unexpected value")
    if errors:
        raise GenerateError("Template data validation failed:\n- " + "\n- ".join(errors))
    return result


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


def _get_path(data: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    return True, current


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = data
    for part in parts[:-1]:
        nested = current.setdefault(part, {})
        if not isinstance(nested, dict):
            raise GenerateError(f"Cannot apply default for {path!r}: {part!r} is not an object")
        current = nested
    current[parts[-1]] = value


def _matches_type(value: Any, expected: TemplateValueType, image_type: type, formula_type: type) -> bool:
    if expected is TemplateValueType.ANY:
        return True
    if expected is TemplateValueType.STRING:
        return isinstance(value, str)
    if expected is TemplateValueType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is TemplateValueType.NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected is TemplateValueType.BOOLEAN:
        return isinstance(value, bool)
    if expected is TemplateValueType.ARRAY:
        return isinstance(value, (list, tuple))
    if expected is TemplateValueType.OBJECT:
        return isinstance(value, dict)
    if expected is TemplateValueType.IMAGE:
        from textalchemy.core.document_model import Image

        return isinstance(value, (image_type, Image))
    if expected is TemplateValueType.FORMULA:
        from textalchemy.core.document_model import Formula

        return isinstance(value, (formula_type, Formula))
    return False


def _coerce_typed_value(value: Any, expected: TemplateValueType, image_type: type, formula_type: type) -> Any:
    if expected is TemplateValueType.IMAGE and not isinstance(value, image_type):
        if isinstance(value, str):
            return image_type(source=value)
        if isinstance(value, dict):
            return image_type(**value)
    if expected is TemplateValueType.FORMULA and not isinstance(value, formula_type):
        from textalchemy.core.document_model import FormulaFormat

        if isinstance(value, str):
            return formula_type(value=value)
        if isinstance(value, dict):
            options = dict(value)
            if "format" in options:
                options["format"] = FormulaFormat(options["format"])
            return formula_type(**options)
    return value


__all__ = [
    "TemplateField",
    "TemplateSchema",
    "TemplateValueType",
    "load_template_data",
    "load_template_schema",
    "validate_template_data",
]
