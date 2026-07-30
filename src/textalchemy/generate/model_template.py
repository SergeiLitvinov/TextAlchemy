"""Безопасный шаблонизатор для богатой модели документа.

Поддерживает ``{{ value }}``, структурные блоки ``{% if ... %}`` и
``{% for item in items %}``, а также типизированные изображения и формулы.
Управляющие конструкции должны находиться в отдельных абзацах или строках
таблицы, чтобы структура документа оставалась однозначной.
"""

from __future__ import annotations

import copy
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from jinja2 import StrictUndefined, TemplateSyntaxError, Undefined, meta
from jinja2.sandbox import SandboxedEnvironment

from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import (
    Block,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    Paragraph,
    Resource,
    ResourceKind,
    Table,
    TableRow,
    TextRun,
)
from textalchemy.core.exceptions import GenerateError

_CONTROL_RE = re.compile(r"^\s*{%\s*(if|for|else|endif|endfor)\b(.*?)%}\s*$", re.DOTALL)
_VALUE_RE = re.compile(r"^\s*{{\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*}}\s*$")
T = TypeVar("T")


@dataclass(frozen=True)
class TemplateImage:
    data: bytes | None = None
    source: str | Path | None = None
    media_type: str | None = None
    filename: str | None = None
    alt_text: str = ""
    width_pt: float | None = None
    height_pt: float | None = None


@dataclass(frozen=True)
class TemplateFormula:
    value: str
    format: FormulaFormat = FormulaFormat.LATEX
    fallback_text: str = ""
    display: bool = False


@dataclass
class TemplateInspection:
    references: dict[str, list[str]]
    errors: list[str]
    warnings: list[str]

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def required_variables(self) -> list[str]:
        return sorted(self.references)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "required_variables": self.required_variables,
            "references": self.references,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def render_document_template(
    template: DocumentModel,
    data: dict[str, Any],
    *,
    strict: bool = True,
    schema: Any = None,
) -> DocumentModel:
    """Вернуть новую модель; исходный шаблон не изменяется."""

    if schema is not None:
        from textalchemy.generate.template_schema import validate_template_data

        data = validate_template_data(schema, data)
    environment = SandboxedEnvironment(
        autoescape=False,
        undefined=StrictUndefined if strict else Undefined,
    )
    model = copy.deepcopy(template)
    renderer = _Renderer(model, environment)
    try:
        model.metadata = renderer.render_mapping(model.metadata, data)
        for section in model.sections:
            for collection_name in (
                "blocks",
                "headers",
                "footers",
                "first_page_headers",
                "first_page_footers",
                "even_page_headers",
                "even_page_footers",
            ):
                setattr(section, collection_name, renderer.render_blocks(getattr(section, collection_name), data))
    except GenerateError:
        raise
    except Exception as error:
        raise GenerateError(f"Failed to render document template: {error}") from error
    errors = model.validate()
    if errors:
        raise GenerateError("Rendered document is invalid: " + "; ".join(errors))
    return model


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


def inspect_document_template(template: DocumentModel, schema: Any = None) -> TemplateInspection:
    """Найти зависимости и структурные ошибки без подстановки данных."""

    environment = SandboxedEnvironment(autoescape=False, undefined=StrictUndefined)
    inspector = _Inspector(environment)
    inspector.inspect_mapping(template.metadata, "metadata", set())
    for section_index, section in enumerate(template.sections):
        base = f"sections[{section_index}]"
        for collection_name in (
            "blocks",
            "headers",
            "footers",
            "first_page_headers",
            "first_page_footers",
            "even_page_headers",
            "even_page_footers",
        ):
            inspector.inspect_blocks(getattr(section, collection_name), f"{base}.{collection_name}", set())
    if schema is not None:
        from textalchemy.generate.template_schema import TemplateSchema

        if isinstance(schema, dict):
            schema = TemplateSchema.from_dict(schema)
        declared = {field.name.split(".", 1)[0] for field in schema.fields}
        referenced = set(inspector.references)
        for name in sorted(referenced - declared):
            inspector.errors.append(f"{name}: referenced by template but not declared in schema")
        for name in sorted(declared - referenced):
            inspector.warnings.append(f"{name}: declared in schema but not used by template")
    return TemplateInspection(
        references=inspector.references,
        errors=inspector.errors,
        warnings=inspector.warnings,
    )


class _Inspector:
    def __init__(self, environment: SandboxedEnvironment):
        self.environment = environment
        self.references: dict[str, list[str]] = {}
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def inspect_blocks(self, blocks: list[Block], location: str, bound: set[str]) -> None:
        self._inspect_sequence(blocks, location, bound, _Renderer._block_marker, self._inspect_block)

    def _inspect_block(self, block: Block, location: str, bound: set[str]) -> None:
        if isinstance(block, Paragraph):
            for index, item in enumerate(block.content):
                if isinstance(item, TextRun):
                    self.inspect_string(item.text, f"{location}.content[{index}]", bound)
                    self.inspect_mapping(item.properties, f"{location}.content[{index}].properties", bound)
            self.inspect_mapping(block.properties, f"{location}.properties", bound)
        elif isinstance(block, Table):
            self._inspect_sequence(block.rows, f"{location}.rows", bound, _Renderer._row_marker, self._inspect_row)
            self.inspect_mapping(block.properties, f"{location}.properties", bound)

    def _inspect_row(self, row: TableRow, location: str, bound: set[str]) -> None:
        for cell_index, cell in enumerate(row.cells):
            self.inspect_blocks(cell.blocks, f"{location}.cells[{cell_index}].blocks", bound)
            self.inspect_mapping(cell.properties, f"{location}.cells[{cell_index}].properties", bound)
        self.inspect_mapping(row.properties, f"{location}.properties", bound)

    def _inspect_sequence(
        self,
        values: list[T],
        location: str,
        bound: set[str],
        marker_getter: Any,
        inspect_item: Any,
    ) -> None:
        index = 0
        while index < len(values):
            item_location = f"{location}[{index}]"
            marker = marker_getter(values[index])
            if marker is None:
                inspect_item(values[index], item_location, bound)
                index += 1
                continue
            command, expression = marker
            if command in {"else", "endif", "endfor"}:
                self.errors.append(f"{item_location}: unexpected {command}")
                index += 1
                continue
            try:
                else_index, end_index = _find_boundary(values, index, command, marker_getter)
            except GenerateError as error:
                self.errors.append(f"{item_location}: {error}")
                return
            if command == "if":
                self.inspect_expression(expression, item_location, bound)
                first_stop = else_index if else_index is not None else end_index
                self._inspect_sequence(values[index + 1 : first_stop], item_location, bound, marker_getter, inspect_item)
                if else_index is not None:
                    self._inspect_sequence(values[else_index + 1 : end_index], item_location, bound, marker_getter, inspect_item)
            else:
                try:
                    variable, iterable = _parse_for(expression)
                    self.inspect_expression(iterable, item_location, bound)
                    self._inspect_sequence(
                        values[index + 1 : end_index],
                        item_location,
                        bound | {variable},
                        marker_getter,
                        inspect_item,
                    )
                except GenerateError as error:
                    self.errors.append(f"{item_location}: {error}")
            index = end_index + 1

    def inspect_expression(self, expression: str, location: str, bound: set[str]) -> None:
        self.inspect_string("{{ " + expression + " }}", location, bound)

    def inspect_string(self, value: str, location: str, bound: set[str]) -> None:
        if "{{" not in value and "{%" not in value:
            return
        try:
            syntax = self.environment.parse(value)
        except TemplateSyntaxError as error:
            self.errors.append(f"{location}: {error.message}")
            return
        for name in sorted(meta.find_undeclared_variables(syntax) - bound):
            self.references.setdefault(name, []).append(location)

    def inspect_mapping(self, value: Any, location: str, bound: set[str]) -> None:
        if isinstance(value, str):
            self.inspect_string(value, location, bound)
        elif isinstance(value, dict):
            for key, item in value.items():
                self.inspect_mapping(item, f"{location}.{key}", bound)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self.inspect_mapping(item, f"{location}[{index}]", bound)


class _Renderer:
    def __init__(self, model: DocumentModel, environment: SandboxedEnvironment):
        self.model = model
        self.environment = environment

    def render_blocks(self, blocks: list[Block], context: dict[str, Any]) -> list[Block]:
        expanded = self._render_sequence(blocks, context, self._block_marker, self._render_block)
        return [block for block in expanded if block is not None]

    def _render_block(self, block: Block, context: dict[str, Any]) -> Block | None:
        if isinstance(block, Paragraph):
            content = []
            for item in block.content:
                if isinstance(item, TextRun):
                    content.extend(self._render_run(item, context))
                else:
                    content.append(item)
            block.content = content
            block.properties = self.render_mapping(block.properties, context)
        elif isinstance(block, Table):
            block.rows = self._render_sequence(block.rows, context, self._row_marker, self._render_row)
            block.properties = self.render_mapping(block.properties, context)
        return block

    def _render_row(self, row: TableRow, context: dict[str, Any]) -> TableRow:
        for cell in row.cells:
            cell.blocks = self.render_blocks(cell.blocks, context)
            cell.properties = self.render_mapping(cell.properties, context)
        row.properties = self.render_mapping(row.properties, context)
        return row

    def _render_run(self, run: TextRun, context: dict[str, Any]) -> list[TextRun | Formula | Image]:
        exact = _VALUE_RE.match(run.text)
        if exact:
            value = self._resolve(exact.group(1), context)
            if isinstance(value, TemplateImage):
                return [self._template_image(value)]
            if isinstance(value, TemplateFormula):
                return [Formula(value.value, value.format, value.display, value.fallback_text)]
            if isinstance(value, (Image, Formula)):
                return [copy.deepcopy(value)]
        run.text = self.environment.from_string(run.text).render(context)
        run.properties = self.render_mapping(run.properties, context)
        return [run]

    def _template_image(self, value: TemplateImage) -> Image:
        raw, source = _image_content(value)
        identity = raw if raw is not None else str(source).encode("utf-8")
        resource_id = f"template-image-{hashlib.sha256(identity).hexdigest()[:16]}"
        media_type = value.media_type or _guess_media_type(value.filename or str(source or ""))
        vector_types = {"image/svg+xml", "image/x-emf", "image/x-wmf"}
        kind = ResourceKind.VECTOR_IMAGE if media_type in vector_types else ResourceKind.RASTER_IMAGE
        if resource_id not in self.model.resources:
            self.model.add_resource(
                Resource(
                    id=resource_id,
                    kind=kind,
                    media_type=media_type,
                    data=raw,
                    source=str(source) if source is not None else None,
                    filename=value.filename or (Path(source).name if source is not None else None),
                )
            )
        box = None
        if value.width_pt is not None or value.height_pt is not None:
            from textalchemy.core.document_model import Box

            box = Box(0, 0, value.width_pt or 0, value.height_pt or 0)
        return Image(resource_id, alt_text=value.alt_text, box=box)

    def _render_sequence(
        self,
        values: list[T],
        context: dict[str, Any],
        marker_getter: Any,
        render_item: Any,
    ) -> list[T]:
        result: list[T] = []
        index = 0
        while index < len(values):
            marker = marker_getter(values[index])
            if marker is None:
                rendered = render_item(copy.deepcopy(values[index]), context)
                if rendered is not None:
                    result.append(rendered)
                index += 1
                continue
            command, expression = marker
            if command in {"else", "endif", "endfor"}:
                raise GenerateError(f"Unexpected template marker: {command}")
            else_index, end_index = _find_boundary(values, index, command, marker_getter)
            if command == "if":
                condition = bool(self._evaluate(expression, context))
                start = index + 1 if condition else (else_index + 1 if else_index is not None else end_index)
                stop = else_index if condition and else_index is not None else end_index
                result.extend(self._render_sequence(values[start:stop], context, marker_getter, render_item))
            else:
                variable, iterable_expression = _parse_for(expression)
                iterable = self._evaluate(iterable_expression, context)
                if iterable is None:
                    iterable = []
                for item in iterable:
                    nested = dict(context)
                    nested[variable] = item
                    result.extend(self._render_sequence(values[index + 1 : end_index], nested, marker_getter, render_item))
            index = end_index + 1
        return result

    def _evaluate(self, expression: str, context: dict[str, Any]) -> Any:
        try:
            return self.environment.compile_expression(expression, undefined_to_none=False)(**context)
        except Exception as error:
            raise GenerateError(f"Invalid template expression {expression!r}: {error}") from error

    def _resolve(self, expression: str, context: dict[str, Any]) -> Any:
        return self._evaluate(expression, context)

    def render_mapping(self, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return self.environment.from_string(value).render(context)
        if isinstance(value, dict):
            return {key: self.render_mapping(item, context) for key, item in value.items()}
        if isinstance(value, list):
            return [self.render_mapping(item, context) for item in value]
        return value

    @staticmethod
    def _block_marker(block: Block) -> tuple[str, str] | None:
        if not isinstance(block, Paragraph):
            return None
        return _marker(block.plain_text)

    @staticmethod
    def _row_marker(row: TableRow) -> tuple[str, str] | None:
        if len(row.cells) != 1 or len(row.cells[0].blocks) != 1:
            return None
        block = row.cells[0].blocks[0]
        if not isinstance(block, Paragraph):
            return None
        return _marker(block.plain_text)


def _marker(value: str) -> tuple[str, str] | None:
    match = _CONTROL_RE.match(value)
    if not match:
        return None
    return match.group(1), match.group(2).strip()


def _find_boundary(values: list[T], start: int, command: str, marker_getter: Any) -> tuple[int | None, int]:
    expected_end = "endif" if command == "if" else "endfor"
    depth = 0
    else_index = None
    for index in range(start + 1, len(values)):
        marker = marker_getter(values[index])
        if marker is None:
            continue
        current = marker[0]
        if current == command:
            depth += 1
        elif current == expected_end:
            if depth == 0:
                return else_index, index
            depth -= 1
        elif current == "else" and command == "if" and depth == 0:
            else_index = index
    raise GenerateError(f"Missing template marker: {expected_end}")


def _parse_for(expression: str) -> tuple[str, str]:
    match = re.match(r"^([A-Za-z_]\w*)\s+in\s+(.+)$", expression, re.DOTALL)
    if not match:
        raise GenerateError(f"Invalid for expression: {expression!r}")
    return match.group(1), match.group(2).strip()


def _image_content(value: TemplateImage) -> tuple[bytes | None, Path | None]:
    if value.data is not None:
        return value.data, None
    if value.source is None:
        raise GenerateError("TemplateImage requires data or source")
    source = Path(value.source)
    if not source.is_file():
        raise GenerateError(f"Template image not found: {source}")
    return source.read_bytes(), source


def _guess_media_type(filename: str) -> str:
    media_type, _ = mimetypes.guess_type(filename)
    if not media_type or not media_type.startswith("image/"):
        raise GenerateError(f"Cannot determine image media type for {filename!r}")
    return media_type


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
