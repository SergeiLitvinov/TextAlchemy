"""Генерация черновика или файла без зависимости от HTTP и состояния Web-приложения."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.exceptions import GenerateError
from textalchemy.generate import generate_document
from textalchemy.generate.model_template import generate_docx_template, generate_html_template, generate_pdf_template
from textalchemy.generate.template_schema import TemplateSchema, validate_template_data
from textalchemy.web.services.generated_preview import prepare_draft_preview
from textalchemy.web.services.generator_catalog import (
    FORMAT_SUFFIX,
    MEDIA_TYPES,
    _output_name,
    _parse_validation_errors,
    _prepare_web_params,
    resolve_web_template,
    template_schema_for,
)
from textalchemy.web.services.template_source import fill_text_package


@dataclass(frozen=True)
class GeneratedFile:
    """Готовый файл; потребитель освобождает временные файлы после передачи результата."""

    path: Path
    media_type: str
    cleanup: Callable[[], None]


Renderer = Callable[..., ConversionReport]


@dataclass
class GeneratorService:
    """Прикладной сценарий с подменяемыми границами файлов, схемы и хранения предпросмотра."""

    store_generated_preview: Callable[[Path, str], dict[str, Any]]
    schema_provider: Callable[[str], tuple[TemplateSchema, str]] = template_schema_for
    resolve_template: Callable[[str], Path] = resolve_web_template
    workspace_factory: Callable[[], ArtifactWorkspace] = ArtifactWorkspace
    generate_docx_template: Renderer = generate_docx_template
    generate_html_template: Renderer = generate_html_template
    generate_pdf_template: Renderer = generate_pdf_template
    fill_text_package: Callable[..., bool] = fill_text_package
    generate_document: Callable[..., Any] = generate_document

    def generate(
        self, *, template: str, output: str = "output.docx", format: str = "docx", params: str = "{}", preview: bool = False
    ) -> GeneratedFile | dict[str, Any]:
        """Проверить данные и вернуть файл или сохранённый предпросмотр; ошибки не оставляют артефактов."""
        fmt = format if format in MEDIA_TYPES else "docx"
        try:
            parsed = json.loads(params) if params else {}
        except json.JSONDecodeError as error:
            return {"success": False, "error": f"Некорректный JSON параметров: {error}"}
        try:
            schema, _ = self.schema_provider(template)
        except GenerateError as error:
            return {"success": False, "error": str(error)}
        if not isinstance(parsed, dict):
            return {"success": False, "error": "Параметры должны быть JSON-объектом"}
        try:
            prepared = _prepare_web_params(schema, parsed)
            missing = []
            if preview:
                validated, schema, missing = prepare_draft_preview(schema, prepared)
            else:
                validated = validate_template_data(schema, prepared)
        except (GenerateError, ValueError, TypeError) as error:
            return {"success": False, "errors": _parse_validation_errors(str(error)), "error": str(error)}

        try:
            workspace = self.workspace_factory()
        except OSError as error:
            return {"success": False, "error": str(error)}
        try:
            if missing:
                output = "Черновик — " + Path(output).name
            out_path = workspace.artifact_path(_output_name(Path(output).name, fmt), fallback=f"output{FORMAT_SUFFIX[fmt]}")
            template_path = self.resolve_template(template)
            if template_path.suffix.lower() == ".docx":
                if fmt == "html":
                    report = self.generate_html_template(template_path, out_path, validated, strict=True, schema=schema)
                elif fmt == "pdf":
                    report = self.generate_pdf_template(template_path, out_path, validated, strict=True, schema=schema)
                elif self.fill_text_package(template_path, out_path, validated):
                    report = None
                else:
                    report = self.generate_docx_template(template_path, out_path, validated, strict=True, schema=schema)
                result = report.output_path if report else out_path
            else:
                if fmt != "docx":
                    raise ValueError("Формат HTML/PDF доступен только для DOCX-шаблонов")
                self.generate_document(template, out_path, validated)
                result = out_path
            workspace.validate_artifact(result)
            if preview:
                try:
                    return {**self.store_generated_preview(result, fmt), "draft": bool(missing), "missing_fields": missing}
                finally:
                    workspace.cleanup()
            return GeneratedFile(result, MEDIA_TYPES[fmt], workspace.cleanup)
        except Exception as error:  # noqa: BLE001
            workspace.cleanup()
            return {"success": False, "error": str(error)}
