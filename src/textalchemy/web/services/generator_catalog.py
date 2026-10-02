"""Каталог шаблонов, схема полей и подготовка входных значений генератора."""

from __future__ import annotations

import base64
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textalchemy.core.document_model import FormulaFormat
from textalchemy.generate import list_templates
from textalchemy.generate.model_template import TemplateFormula, TemplateImage, inspect_document_template
from textalchemy.generate.template import DocumentTemplate, TemplateEngine
from textalchemy.generate.template_schema import TemplateField, TemplateSchema, TemplateValueType, load_template_schema
from textalchemy.web.services.template_variables import custom_path, custom_templates

MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
}
FORMAT_SUFFIX = {"docx": ".docx", "html": ".html", "pdf": ".pdf"}


def resolve_web_template(name: str, templates_dir: str | Path | None = None) -> Path:
    return custom_path(name) if name.startswith("edited-") else TemplateEngine(templates_dir).resolve_template(name)


def template_schema_for(name: str, templates_dir: str | Path | None = None) -> tuple[TemplateSchema, str]:
    """Вернуть (схема, источник) для шаблона: sidecar-файл или авто-деривация."""
    template_path = resolve_web_template(name, templates_dir)
    stem = template_path.stem
    for suffix in (".json", ".yaml", ".yml", ".toml"):
        sidecar = template_path.with_name(f"{stem}.schema{suffix}")
        if sidecar.is_file():
            return load_template_schema(sidecar), "sidecar"
    if template_path.suffix.lower() == ".docx":
        from textalchemy.formats.docx import read_docx_model

        model = read_docx_model(template_path)
        inspection = inspect_document_template(model)
        fields = [
            TemplateField(variable, TemplateValueType.STRING, required=False, description="")
            for variable in inspection.required_variables
        ]
        return TemplateSchema(fields=fields, allow_extra=True), "derived"
    return TemplateSchema(fields=[], allow_extra=True), "derived"


def _parse_validation_errors(message: str) -> dict[str, str]:
    """Разобрать сообщение GenerateError в карту {поле: ошибка}."""
    errors: dict[str, str] = {}
    for line in message.splitlines():
        line = line.strip()
        if line.startswith("- "):
            line = line[2:]
        if ": " in line:
            field, _, detail = line.partition(": ")
            errors.setdefault(field, detail)
    return errors


def _decode_data_uri(uri: str) -> TemplateImage:
    header, _, payload = uri.partition(",")
    media_type = header.removeprefix("data:").split(";")[0] or "image/png"
    return TemplateImage(data=base64.b64decode(payload), media_type=media_type, filename="upload")


def _prepare_web_params(schema: TemplateSchema, params: dict[str, Any]) -> dict[str, Any]:
    """Заменить data-URI изображений на TemplateImage до валидации."""
    result = dict(params)
    for field in schema.fields:
        if field.type is TemplateValueType.FORMULA:
            value = result.get(field.name)
            if isinstance(value, str) and value.lstrip().startswith("<math"):
                result[field.name] = TemplateFormula(value=value, format=FormulaFormat.MATHML)
        if field.type is not TemplateValueType.IMAGE:
            continue
        value = result.get(field.name)
        if isinstance(value, str) and value.startswith("data:"):
            result[field.name] = _decode_data_uri(value)
    return result


def _output_name(name: str, fmt: str) -> str:
    stem = Path(name).stem or "output"
    return f"{stem}{FORMAT_SUFFIX[fmt]}"


def _template_preview_dir(name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return Path(tempfile.gettempdir()) / "textalchemy_generate_preview" / safe


@dataclass
class GeneratorCatalogService:
    """Описание доступных шаблонов и их текущей схемы для любого потребителя приложения."""

    builtins: Callable[[], list[DocumentTemplate]] = list_templates
    custom: Callable[[], list[dict[str, Any]]] = custom_templates
    schema_provider: Callable[[str], tuple[TemplateSchema, str]] = template_schema_for

    def list(self) -> list[dict[str, Any]]:
        return [
            {"name": item.name, "description": item.description, "template_type": item.template_type} for item in self.builtins()
        ] + self.custom()

    def schema(self, name: str) -> dict[str, Any]:
        schema, source = self.schema_provider(name)
        description = next((item["description"] for item in self.list() if item["name"] == name), name)
        return {"name": name, "description": description, "source": source, "schema": schema.to_dict()}
