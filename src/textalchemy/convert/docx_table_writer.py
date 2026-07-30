"""DOCX table exporter for spans, geometry, fills, margins, and styles."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import Block, DocumentModel, Table
from textalchemy.core.properties import TableCellProperties, TableProperties, TableRowProperties

BlockWriter = Callable[
    [Any, list[Block], DocumentModel, ConversionReport, str, dict[str, int]],
    None,
]


def write_table(
    container: Any,
    source: Table,
    document: DocumentModel,
    report: ConversionReport,
    location: str,
    counters: dict[str, int],
    write_blocks: BlockWriter,
) -> None:
    column_count = max((sum(max(cell.column_span, 1) for cell in row.cells) for row in source.rows), default=1)
    row_count = max(len(source.rows), 1)
    try:
        target = container.add_table(rows=row_count, cols=column_count)
    except TypeError:
        from docx.shared import Inches

        target = container.add_table(rows=row_count, cols=column_count, width=Inches(6))
    _apply_table_properties(target, source.properties)
    if source.style_id:
        _set_table_style_id(target, source.style_id)
    elif source.properties.style_name:
        try:
            target.style = source.properties.style_name
        except KeyError:
            report.add(
                IssueSeverity.WARNING,
                "table-style",
                f"style {source.properties.style_name!r} is unavailable",
                location,
            )
    for row_index, source_row in enumerate(source.rows):
        _apply_row_properties(target.rows[row_index], source_row.properties)
        column_index = 0
        for cell_index, source_cell in enumerate(source_row.cells):
            span = max(source_cell.column_span, 1)
            target_cell = target.cell(row_index, column_index)
            if span > 1:
                target_cell = target_cell.merge(target.cell(row_index, min(column_index + span - 1, column_count - 1)))
            _apply_cell_properties(target_cell, source_cell.properties)
            _clear_container(target_cell)
            write_blocks(
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


def _clear_container(container: Any) -> None:
    from lxml import etree

    element = container._element
    for child in list(element):
        if etree.QName(child).localname in {"p", "tbl"}:
            element.remove(child)


def _set_table_style_id(table: Any, style_id: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = table._tbl.tblPr
    style = properties.find(qn("w:tblStyle"))
    if style is None:
        style = OxmlElement("w:tblStyle")
        properties.insert(0, style)
    style.set(qn("w:val"), style_id)


def _apply_table_properties(table: Any, properties: TableProperties) -> None:
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn

    if properties.autofit is not None:
        table.autofit = properties.autofit
    if properties.alignment:
        alignment = getattr(WD_TABLE_ALIGNMENT, properties.alignment.upper(), None)
        if alignment is not None:
            table.alignment = alignment
    columns = table._tbl.xpath("./w:tblGrid/w:gridCol")
    for column, width in zip(columns, properties.grid_widths_twips, strict=False):
        column.set(qn("w:w"), str(width))


def _apply_row_properties(row: Any, properties: TableRowProperties) -> None:
    if not properties.repeat_header:
        return
    from docx.oxml import OxmlElement

    row._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))


def _apply_cell_properties(cell: Any, properties: TableCellProperties) -> None:
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    cell_properties = cell._tc.get_or_add_tcPr()
    if properties.fill:
        shading = cell_properties.find(qn("w:shd"))
        if shading is None:
            shading = OxmlElement("w:shd")
            cell_properties.append(shading)
        shading.set(qn("w:fill"), properties.fill)
    if properties.width_twips is not None:
        width = cell_properties.get_or_add_tcW()
        width.set(qn("w:type"), "dxa")
        width.set(qn("w:w"), str(properties.width_twips))
    if properties.margins_twips:
        margin_node = cell_properties.first_child_found_in("w:tcMar")
        if margin_node is None:
            margin_node = OxmlElement("w:tcMar")
            cell_properties.append(margin_node)
        for edge, value in properties.margins_twips.items():
            node = margin_node.find(qn(f"w:{edge}"))
            if node is None:
                node = OxmlElement(f"w:{edge}")
                margin_node.append(node)
            node.set(qn("w:w"), str(value))
            node.set(qn("w:type"), "dxa")
    if properties.vertical_alignment:
        alignment = getattr(WD_CELL_VERTICAL_ALIGNMENT, properties.vertical_alignment.upper(), None)
        if alignment is not None:
            cell.vertical_alignment = alignment


__all__ = ["write_table"]
