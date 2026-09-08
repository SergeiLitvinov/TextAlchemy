"""Editable table cells, including paragraph structure and explicit cell appearance."""

from textalchemy.core.document_model import Paragraph, Table, TableCell, TableRow
from textalchemy.formats.pptx_paragraph import frame_metadata, paragraph_metadata

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def read_table(element, box, slide_part, theme_colors, parse_runs, resolve_color, alignments):
    rows = []
    for row in element.findall(A + "tr"):
        cells = []
        for cell in row.findall(A + "tc"):
            blocks = []
            for paragraph in cell.findall(A + "txBody/" + A + "p"):
                content = []
                parse_runs(paragraph, content, slide_part, theme_colors=theme_colors)
                meta = paragraph_metadata(paragraph, alignments)
                blocks.append(
                    Paragraph(
                        content,
                        alignment=meta.get("alignment"),
                        properties={
                            "pptx": {
                                "paragraphs": [meta],
                                "text_frame": frame_metadata(cell.find(A + "txBody")),
                            }
                        },
                    )
                )
            settings = _cell_settings(cell.find(A + "tcPr"), theme_colors, resolve_color)
            cells.append(TableCell(blocks, int(cell.get("rowSpan", "1")), int(cell.get("gridSpan", "1")), settings))
        rows.append(TableRow(cells, {"height_pt": float(row.get("h", "0")) / 12700}))
    properties = {}
    grid = element.find(A + "tblGrid")
    if grid is not None:
        properties["column_widths_pt"] = [float(column.get("w", "0")) / 12700 for column in grid]
    return Table(rows, box=box, properties=properties)


def _cell_settings(properties, colors, resolve):
    if properties is None:
        return {}
    result = {}
    for key, side in (("marL", "left"), ("marR", "right"), ("marT", "top"), ("marB", "bottom")):
        if properties.get(key) is not None:
            result.setdefault("margins_twips", {})[side] = round(float(properties.get(key)) / 635)
    if properties.get("anchor") is not None:
        result["vertical_alignment"] = {"t": "top", "ctr": "center", "b": "bottom"}.get(properties.get("anchor"))
    fill = properties.find(A + "solidFill")
    if fill is not None:
        color, _ = resolve(fill, colors)
        if color:
            result["fill"] = color.to_hex()
            result["fill_color"] = color.to_dict()
    elif properties.find(A + "noFill") is not None:
        result["fill"] = "none"
    borders = {}
    for tag in ("lnL", "lnR", "lnT", "lnB", "lnTlToBr", "lnBlToTr"):
        line = properties.find(A + tag)
        if line is None:
            continue
        border = {"width_pt": float(line.get("w", "12700")) / 12700}
        if line.find(A + "noFill") is not None:
            border["none"] = True
        solid = line.find(A + "solidFill")
        if solid is not None:
            color, _ = resolve(solid, colors)
            if color:
                border["color"] = color.to_dict()
        dash = line.find(A + "prstDash")
        if dash is not None:
            border["dash"] = dash.get("val")
        borders[tag] = border
    if borders:
        result["pptx_borders"] = borders
    return result
