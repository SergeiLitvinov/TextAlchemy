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
    VECTOR_IMAGE_MEDIA_TYPES,
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
_TEMPLATE_BUILTINS = frozenset({"toc", "bibliography", "id", "ref"})
_TOKEN_RE = re.compile(r"⟪TA:(REF|ID|TOC|BIB)(?:\|([^⟫]+))?⟫")
_KIND_LABELS = {"fig": "Рис. ", "tbl": "Табл. ", "sec": ""}
T = TypeVar("T")


def _token(kind: str, payload: str = "") -> str:
    return f"⟪TA:{kind}|{payload}⟫" if payload else f"⟪TA:{kind}⟫"


def _template_helpers() -> dict[str, Any]:
    return {
        "toc": lambda: _token("TOC"),
        "bibliography": lambda: _token("BIB"),
        "id": lambda label: _token("ID", str(label)),
        "ref": lambda label: _token("REF", str(label)),
    }


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
    context = dict(data)
    context.update(_template_helpers())
    model = copy.deepcopy(template)
    renderer = _Renderer(model, environment)
    try:
        model.metadata = renderer.render_mapping(model.metadata, context)
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
                setattr(section, collection_name, renderer.render_blocks(getattr(section, collection_name), context))
        _apply_auto_content(model, data)
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
        for name in sorted(meta.find_undeclared_variables(syntax) - bound - _TEMPLATE_BUILTINS):
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
        kind = ResourceKind.VECTOR_IMAGE if media_type in VECTOR_IMAGE_MEDIA_TYPES else ResourceKind.RASTER_IMAGE
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


def _apply_auto_content(model: DocumentModel, data: dict[str, Any]) -> None:
    """Разрешить ``{{ toc() }}``, ``{{ bibliography() }}``, ``{{ id(...) }}`` и ``{{ ref(...) }}``.

    Запускается после основного рендера, когда структура документа (заголовки,
    подписи) уже известна: маркеры становятся токенами, которые здесь заменяются
    оглавлением, списком литературы и номерами перекрёстных ссылок.
    """
    targets: dict[str, str] = {}
    references: dict[str, str] = {}
    counters: dict[str, int] = {}
    toc_markers: list[Paragraph] = []
    bib_markers: list[Paragraph] = []
    headings: list[tuple[int, str, int]] = []
    for section_index, section in enumerate(model.sections, start=1):
        _scan_auto_blocks(section.blocks, section_index, targets, references, counters, toc_markers, bib_markers, headings)
    for section in model.sections:
        _resolve_ref_blocks(section.blocks, targets, references)
    toc_paragraphs = _build_toc(headings) if toc_markers else []
    bib_paragraphs = _build_bibliography(data) if bib_markers else []
    for section in model.sections:
        section.blocks = _replace_markers(section.blocks, toc_markers, toc_paragraphs, bib_markers, bib_paragraphs)


def _scan_auto_blocks(
    blocks: list[Block],
    section_index: int,
    targets: dict[str, str],
    references: dict[str, str],
    counters: dict[str, int],
    toc_markers: list[Paragraph],
    bib_markers: list[Paragraph],
    headings: list[tuple[int, str, int]],
) -> None:
    for block in blocks:
        if isinstance(block, Table):
            for row in block.rows:
                for cell in row.cells:
                    _scan_auto_blocks(
                        cell.blocks, section_index, targets, references, counters, toc_markers, bib_markers, headings
                    )
            continue
        if not isinstance(block, Paragraph):
            continue
        for run in block.content:
            if isinstance(run, TextRun):
                _record_id_targets(run.text, targets, references, counters)
        plain = _TOKEN_RE.sub(_plain_replacer(targets, references), block.plain_text).strip()
        marker = _TOKEN_RE.fullmatch(plain)
        if marker is not None:
            if marker.group(1) == "TOC":
                toc_markers.append(block)
            elif marker.group(1) == "BIB":
                bib_markers.append(block)
            continue
        level = _heading_level(block)
        if level is not None:
            headings.append((level, plain, section_index))


def _record_id_targets(text: str, targets: dict[str, str], references: dict[str, str], counters: dict[str, int]) -> None:
    for match in _TOKEN_RE.finditer(text):
        if match.group(1) != "ID" or not match.group(2):
            continue
        label = match.group(2)
        if label in targets:
            continue
        kind = label.split(":", 1)[0] if ":" in label else "item"
        number = counters.get(kind, 0) + 1
        counters[kind] = number
        targets[label] = str(number)
        references[label] = f"{_KIND_LABELS.get(kind, '')}{number}"


def _plain_replacer(targets: dict[str, str], references: dict[str, str]):
    def replace(match: re.Match[str]) -> str:
        label = match.group(2)
        if match.group(1) == "ID" and label and label in targets:
            return targets[label]
        if label and label in references:
            return references[label]
        return match.group(0)

    return replace


def _resolve_ref_blocks(blocks: list[Block], targets: dict[str, str], references: dict[str, str]) -> None:
    for block in blocks:
        if isinstance(block, Table):
            for row in block.rows:
                for cell in row.cells:
                    _resolve_ref_blocks(cell.blocks, targets, references)
            continue
        if not isinstance(block, Paragraph):
            continue
        for run in block.content:
            if not isinstance(run, TextRun) or "TA:" not in run.text:
                continue
            run.text = _resolve_ref_text(run.text, targets, references)


def _resolve_ref_text(text: str, targets: dict[str, str], references: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        label = match.group(2)
        if match.group(1) == "REF" and (label is None or label not in references):
            raise GenerateError(f"Undefined cross-reference {label!r}")
        if match.group(1) == "ID" and label and label in targets:
            return targets[label]
        if label and label in references:
            return references[label]
        return match.group(0)

    return _TOKEN_RE.sub(replace, text)


def _heading_level(block: Paragraph) -> int | None:
    properties = block.properties or {}
    level = properties.get("heading_level")
    if isinstance(level, int) and 1 <= level <= 6:
        return level
    style = str(properties.get("style_name") or properties.get("style_id") or "").replace("_", " ")
    match = re.match(r"^(?:heading|заголовок)\s*([1-6])$", style, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _build_toc(headings: list[tuple[int, str, int]]) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    for level, text, page in headings:
        indent = "    " * (level - 1)
        dots = "." * max(4, 72 - len(text) - len(str(page)))
        paragraphs.append(
            Paragraph(
                content=[TextRun(text=f"{indent}{text} {dots} {page}")],
                properties={"toc_entry": {"level": level, "page": page}},
            )
        )
    return paragraphs


def _build_bibliography(data: dict[str, Any]) -> list[Paragraph]:
    raw = data.get("bibliography") or data.get("references") or []
    from textalchemy.organize.bibliography import BibItem

    items: list[Any] = []
    for item in raw:
        if isinstance(item, str):
            items.append(item)
        elif isinstance(item, BibItem):
            items.append(item)
        elif isinstance(item, dict):
            items.append(BibItem.from_dict(item))
    paragraphs: list[Paragraph] = []
    for index, item in enumerate(items, start=1):
        paragraphs.append(
            Paragraph(
                content=[TextRun(text=f"[{index}] {_format_reference(item)}")],
                properties={"bibliography_item": {"index": index}},
            )
        )
    if not items:
        paragraphs.append(Paragraph(content=[TextRun("(список литературы пуст)")]))
    return paragraphs


def _format_reference(item: Any) -> str:
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


def _replace_markers(
    blocks: list[Block],
    toc_markers: list[Paragraph],
    toc_paragraphs: list[Paragraph],
    bib_markers: list[Paragraph],
    bib_paragraphs: list[Paragraph],
) -> list[Block]:
    result: list[Block] = []
    for block in blocks:
        if block in toc_markers:
            result.extend(copy.deepcopy(toc_paragraphs))
        elif block in bib_markers:
            result.extend(copy.deepcopy(bib_paragraphs))
        else:
            result.append(block)
    return result


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
