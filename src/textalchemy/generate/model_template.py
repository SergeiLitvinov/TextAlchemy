"""Application adapters for the independent in-memory template API."""

from pathlib import Path
from typing import Any

from opendoc.document_model import DocumentModel

from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.exceptions import GenerateError
from textalchemy.templating import (
    TemplateError,
    TemplateFormula,
    TemplateImage,
    TemplateInspection,
)
from textalchemy.templating import (
    inspect_document_template as _inspect,
)
from textalchemy.templating import (
    render_document_template as _render,
)


def render_document_template(
    template: DocumentModel, data: dict[str, Any], *, strict: bool = True, schema: Any = None
) -> DocumentModel:
    """Render with application file loading and bibliography formatting."""
    try:
        return _render(
            template, data, strict=strict, schema=schema, image_loader=_load_image, reference_formatter=_format_reference
        )
    except TemplateError as error:
        raise GenerateError(str(error)) from error


def inspect_document_template(template: DocumentModel, schema: Any = None) -> TemplateInspection:
    """Inspect a template while preserving the application error contract."""
    try:
        return _inspect(template, schema)
    except TemplateError as error:
        raise GenerateError(str(error)) from error


def _load_image(value: TemplateImage) -> bytes:
    source = Path(value.source)
    if not source.is_file():
        raise TemplateError(f"Template image not found: {source}")
    return source.read_bytes()


def generate_docx_template(
    template_path: str | Path,
    output_path: str | Path,
    data: dict[str, Any],
    *,
    strict: bool = True,
    schema: Any = None,
) -> ConversionReport:
    """Выполнить полный цикл DOCX-шаблона и вернуть ``ConversionReport``."""

    from textalchemy.convert.docx_writer import write_docx_model
    from textalchemy.formats.docx import read_docx_model

    template = read_docx_model(template_path)
    rendered = render_document_template(template, data, strict=strict, schema=schema)
    return write_docx_model(rendered, output_path)


def generate_html_template(
    template_path: str | Path,
    output_path: str | Path,
    data: dict[str, Any],
    *,
    strict: bool = True,
    schema: Any = None,
) -> ConversionReport:
    """Отрендерить DOCX-шаблон в самодостаточный HTML."""

    from textalchemy.convert.html_writer import write_html_model
    from textalchemy.formats.docx import read_docx_model

    template = read_docx_model(template_path)
    rendered = render_document_template(template, data, strict=strict, schema=schema)
    return write_html_model(rendered, output_path)


def generate_pdf_template(
    template_path: str | Path,
    output_path: str | Path,
    data: dict[str, Any],
    *,
    strict: bool = True,
    schema: Any = None,
) -> ConversionReport:
    """Отрендерить DOCX-шаблон в PDF через общую модель документа."""

    from textalchemy.convert.pdf_writer import write_pdf_model
    from textalchemy.formats.docx import read_docx_model

    template = read_docx_model(template_path)
    rendered = render_document_template(template, data, strict=strict, schema=schema)
    return write_pdf_model(rendered, output_path)


def _format_reference(item: Any) -> str | None:
    from textalchemy.organize.bibliography import BibItem

    if isinstance(item, dict):
        item = BibItem.from_dict(item)
    if not isinstance(item, (str, BibItem)):
        return None
    if isinstance(item, str):
        return item.strip()
    try:
        from textalchemy.organize.gost import GostFormatter

        text = GostFormatter().format_item(item).strip()
    except Exception:  # noqa: BLE001
        text = ""
    if text:
        return text
    parts = []
    if getattr(item, "authors", None):
        parts.append(", ".join(item.authors))
    if getattr(item, "title", None):
        parts.append(item.title)
    if getattr(item, "year", None):
        parts.append(str(item.year))
    return " ".join(parts)


__all__ = [
    "TemplateFormula",
    "TemplateImage",
    "TemplateInspection",
    "generate_docx_template",
    "generate_html_template",
    "generate_pdf_template",
    "inspect_document_template",
    "render_document_template",
]
