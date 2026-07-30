"""DOCX table importer for spans, geometry, fills, margins, and styles."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textalchemy.core.document_model import Block, DocumentModel, Table, TableCell, TableRow

BlockReader = Callable[[Any, DocumentModel], list[Block]]


def read_table(table: Any, model: DocumentModel, read_blocks: BlockReader) -> Table:
    from docx.oxml.ns import qn

    rows: list[TableRow] = []
    for row in table.rows:
        cells: list[TableCell] = []
        seen_cells: set[int] = set()
        for cell in row.cells:
            cell_identity = id(cell._tc)
            if cell_identity in seen_cells:
                continue
            seen_cells.add(cell_identity)
            grid_span = cell._tc.xpath("./w:tcPr/w:gridSpan")
            column_span = int(grid_span[0].get(qn("w:val"), "1")) if grid_span else 1
            vertical_merge = cell._tc.xpath("./w:tcPr/w:vMerge")
            properties = _cell_properties(cell)
            if vertical_merge:
                properties["vertical_merge"] = vertical_merge[0].get(qn("w:val"), "continue")
            cells.append(
                TableCell(
                    blocks=read_blocks(cell, model),
                    column_span=column_span,
                    properties=properties,
                )
            )
        row_properties: dict[str, Any] = {}
        if row._tr.xpath("./w:trPr/w:tblHeader"):
            row_properties["repeat_header"] = True
        rows.append(TableRow(cells=cells, properties=row_properties))
    style_id = table.style.style_id if table.style is not None else None
    properties: dict[str, Any] = {"style_name": table.style.name} if table.style is not None else {}
    properties["autofit"] = bool(table.autofit)
    if table.alignment is not None:
        properties["alignment"] = table.alignment.name.lower()
    grid_widths = [
        int(column.get(qn("w:w")))
        for column in table._tbl.xpath("./w:tblGrid/w:gridCol")
        if column.get(qn("w:w"))
    ]
    if grid_widths:
        properties["grid_widths_twips"] = grid_widths
    return Table(rows=rows, style_id=style_id, properties=properties)


def _cell_properties(cell: Any) -> dict[str, Any]:
    from docx.oxml.ns import qn
    from lxml import etree

    properties: dict[str, Any] = {}
    shading = cell._tc.xpath("./w:tcPr/w:shd")
    if shading:
        fill = shading[0].get(qn("w:fill"))
        if fill and fill.lower() != "auto":
            properties["fill"] = fill
    width = cell._tc.xpath("./w:tcPr/w:tcW")
    if width and width[0].get(qn("w:type")) == "dxa":
        properties["width_twips"] = int(width[0].get(qn("w:w"), 0))
    margins = cell._tc.xpath("./w:tcPr/w:tcMar")
    if margins:
        values = {}
        for child in margins[0]:
            value = child.get(qn("w:w"))
            if value is not None:
                values[etree.QName(child).localname] = int(value)
        if values:
            properties["margins_twips"] = values
    if cell.vertical_alignment is not None:
        properties["vertical_alignment"] = cell.vertical_alignment.name.lower()
    return properties


__all__ = ["read_table"]
