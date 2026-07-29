"""Экспорт богатой промежуточной модели в редактируемый DOCX."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import (
    Block,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    Paragraph,
    Resource,
    Section,
    Table,
    TextRun,
    TextStyle,
)


def write_docx_model(document: DocumentModel, output_path: str | Path) -> ConversionReport:
    """Записать ``DocumentModel`` в DOCX и вернуть отчёт о потерях."""

    from docx import Document
    from docx.enum.section import WD_SECTION

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = ConversionReport(output)
    target = Document()
    _write_metadata(target, document.metadata)

    sections = document.sections or [Section()]
    counters = {"paragraphs": 0, "tables": 0, "images": 0, "formulas": 0}
    for section_index, source_section in enumerate(sections):
        if section_index == 0:
            target_section = target.sections[0]
        else:
            target_section = target.add_section(WD_SECTION.NEW_PAGE)
        _apply_page_settings(target_section, source_section)
        _write_header_footer(target_section, source_section, document, report, section_index, counters)
        _write_blocks(target, source_section.blocks, document, report, f"sections[{section_index}]", counters)

    try:
        target.save(output)
    except Exception as error:  # noqa: BLE001 - diagnostic boundary must return a report
        report.add(IssueSeverity.ERROR, "docx-write", str(error))
        return report
    report.metrics.update(counters)
    report.metrics["sections"] = len(sections)
    report.metrics["resources"] = len(document.resources)
    return report


def _write_metadata(target: Any, metadata: dict[str, Any]) -> None:
    properties = target.core_properties
    for name in ("title", "subject", "author", "keywords", "comments"):
        value = metadata.get(name)
        if value is not None:
            setattr(properties, name, str(value))


def _apply_page_settings(target: Any, source: Section) -> None:
    from docx.shared import Pt

    target.page_width = Pt(source.page.width.pt)
    target.page_height = Pt(source.page.height.pt)
    target.top_margin = Pt(source.page.margin_top.pt)
    target.right_margin = Pt(source.page.margin_right.pt)
    target.bottom_margin = Pt(source.page.margin_bottom.pt)
    target.left_margin = Pt(source.page.margin_left.pt)


def _write_header_footer(
    target: Any,
    source: Section,
    document: DocumentModel,
    report: ConversionReport,
    section_index: int,
    counters: dict[str, int],
) -> None:
    target.header.is_linked_to_previous = False
    target.footer.is_linked_to_previous = False
    _clear_container(target.header)
    _clear_container(target.footer)
    _write_blocks(target.header, source.headers, document, report, f"sections[{section_index}].headers", counters)
    _write_blocks(target.footer, source.footers, document, report, f"sections[{section_index}].footers", counters)


def _clear_container(container: Any) -> None:
    from lxml import etree

    element = container._element
    for child in list(element):
        if etree.QName(child).localname in {"p", "tbl"}:
            element.remove(child)


def _write_blocks(
    container: Any,
    blocks: list[Block],
    document: DocumentModel,
    report: ConversionReport,
    location: str,
    counters: dict[str, int],
) -> None:
    for index, block in enumerate(blocks):
        block_location = f"{location}.blocks[{index}]"
        if isinstance(block, Paragraph):
            paragraph = _add_paragraph(container, block, report, block_location)
            _write_paragraph_content(paragraph, block, document, report, block_location, counters)
            counters["paragraphs"] += 1
        elif isinstance(block, Table):
            _add_table(container, block, document, report, block_location, counters)
            counters["tables"] += 1
        elif isinstance(block, Formula):
            paragraph = container.add_paragraph()
            _write_formula(paragraph, block, report, block_location)
            counters["formulas"] += 1
        elif isinstance(block, Image):
            paragraph = container.add_paragraph()
            _write_image(paragraph, block, document, report, block_location)
            counters["images"] += 1


def _add_paragraph(container: Any, source: Paragraph, report: ConversionReport, location: str) -> Any:
    style = source.properties.get("style_name") or source.style_id
    try:
        paragraph = container.add_paragraph(style=style) if style else container.add_paragraph()
    except KeyError:
        paragraph = container.add_paragraph()
        report.add(IssueSeverity.WARNING, "paragraph-style", f"style {style!r} is unavailable", location)
    if source.alignment:
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        alignment = getattr(WD_ALIGN_PARAGRAPH, source.alignment.upper(), None)
        if alignment is not None:
            paragraph.alignment = alignment
    _apply_paragraph_properties(paragraph, source.properties)
    return paragraph


def _apply_paragraph_properties(paragraph: Any, properties: dict[str, Any]) -> None:
    from docx.shared import Pt

    paragraph_format = paragraph.paragraph_format
    for name in ("left_indent", "right_indent", "first_line_indent", "space_before", "space_after"):
        value = properties.get(f"{name}_pt")
        if value is not None:
            setattr(paragraph_format, name, Pt(value))
    if properties.get("line_spacing") is not None:
        paragraph_format.line_spacing = properties["line_spacing"]


def _write_paragraph_content(
    paragraph: Any,
    source: Paragraph,
    document: DocumentModel,
    report: ConversionReport,
    location: str,
    counters: dict[str, int],
) -> None:
    for index, item in enumerate(source.content):
        item_location = f"{location}.content[{index}]"
        if isinstance(item, TextRun):
            run = paragraph.add_run(item.text)
            _apply_text_style(run, item.style)
            if item.link:
                _wrap_hyperlink(paragraph, run, item.link)
        elif isinstance(item, Formula):
            _write_formula(paragraph, item, report, item_location)
            counters["formulas"] += 1
        elif isinstance(item, Image):
            _write_image(paragraph, item, document, report, item_location)
            counters["images"] += 1


def _apply_text_style(run: Any, style: TextStyle) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    if style.font_family:
        run.font.name = style.font_family
    if style.font_size:
        run.font.size = Pt(style.font_size.pt)
    run.bold = style.bold
    run.italic = style.italic
    run.underline = style.underline
    if style.color:
        color = style.color.removeprefix("#")
        if len(color) == 6:
            run.font.color.rgb = RGBColor.from_string(color)
    if style.language:
        run_properties = run._r.get_or_add_rPr()
        language = OxmlElement("w:lang")
        language.set(qn("w:val"), style.language)
        run_properties.append(language)


def _wrap_hyperlink(paragraph: Any, run: Any, url: str) -> None:
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    relationship_id = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)
    run._r.getparent().remove(run._r)
    hyperlink.append(run._r)
    paragraph._p.append(hyperlink)


def _write_formula(paragraph: Any, formula: Formula, report: ConversionReport, location: str) -> None:
    if formula.format is FormulaFormat.OMML:
        from docx.oxml import parse_xml

        try:
            paragraph._p.append(parse_xml(formula.value))
            return
        except Exception as error:  # noqa: BLE001 - malformed foreign XML is reported as a loss
            report.add(IssueSeverity.LOSS, "formula", f"invalid OMML replaced by fallback: {error}", location)
    else:
        report.add(
            IssueSeverity.LOSS,
            "formula",
            f"{formula.format.value} is not natively convertible to OMML; fallback text used",
            location,
        )
    paragraph.add_run(formula.fallback_text or formula.value)


def _write_image(
    paragraph: Any,
    image: Image,
    document: DocumentModel,
    report: ConversionReport,
    location: str,
) -> None:
    from docx.shared import Pt

    resource = document.resources.get(image.resource_id)
    if resource is None:
        report.add(IssueSeverity.ERROR, "image", f"resource {image.resource_id!r} not found", location)
        paragraph.add_run(image.alt_text)
        return
    stream = _resource_stream(resource)
    width = Pt(image.box.width) if image.box and image.box.width > 0 else None
    height = Pt(image.box.height) if image.box and image.box.height > 0 else None
    try:
        shape = paragraph.add_run().add_picture(stream, width=width, height=height)
        if image.alt_text:
            properties = shape._inline.docPr
            properties.set("descr", image.alt_text)
    except Exception as error:  # noqa: BLE001 - image backends raise several library-specific errors
        report.add(
            IssueSeverity.LOSS,
            "image",
            f"{resource.media_type} could not be embedded; alt text used: {error}",
            location,
        )
        paragraph.add_run(image.alt_text or f"[{resource.filename or resource.id}]")


def _resource_stream(resource: Resource) -> BytesIO | str:
    if resource.data is not None:
        return BytesIO(resource.data)
    if resource.source is None:
        raise ValueError(f"resource {resource.id!r} has no content")
    return resource.source


def _add_table(
    container: Any,
    source: Table,
    document: DocumentModel,
    report: ConversionReport,
    location: str,
    counters: dict[str, int],
) -> None:
    column_count = max((sum(max(cell.column_span, 1) for cell in row.cells) for row in source.rows), default=1)
    row_count = max(len(source.rows), 1)
    try:
        target = container.add_table(rows=row_count, cols=column_count)
    except TypeError:
        from docx.shared import Inches

        target = container.add_table(rows=row_count, cols=column_count, width=Inches(6))
    style = source.properties.get("style_name") or source.style_id
    if style:
        try:
            target.style = style
        except KeyError:
            report.add(IssueSeverity.WARNING, "table-style", f"style {style!r} is unavailable", location)
    for row_index, source_row in enumerate(source.rows):
        column_index = 0
        for cell_index, source_cell in enumerate(source_row.cells):
            span = max(source_cell.column_span, 1)
            target_cell = target.cell(row_index, column_index)
            if span > 1:
                target_cell = target_cell.merge(target.cell(row_index, min(column_index + span - 1, column_count - 1)))
            _clear_container(target_cell)
            _write_blocks(
                target_cell,
                source_cell.blocks,
                document,
                report,
                f"{location}.rows[{row_index}].cells[{cell_index}]",
                counters,
            )
            if not source_cell.blocks:
                target_cell.add_paragraph()
            if source_cell.row_span > 1:
                report.add(IssueSeverity.LOSS, "table-row-span", "vertical merge is not yet exported", location)
            column_index += span


__all__ = ["write_docx_model"]
