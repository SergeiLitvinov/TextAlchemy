"""Explicit cell appearance; no dependency on source table style IDs."""

from textalchemy.convert.pptx_text_writer import set_color
from textalchemy.core.diagnostics import IssueSeverity

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def configure_cell(cell, properties, report, location):
    from lxml import etree
    from pptx.dml.color import ColorFormat
    from pptx.enum.text import MSO_ANCHOR
    from pptx.oxml.xmlchemy import OxmlElement
    from pptx.util import Pt

    for side, value in properties.get("margins_twips", {}).items():
        if side in ("left", "right", "top", "bottom"):
            setattr(cell, f"margin_{side}", Pt(value / 20))
    anchors = {"top": MSO_ANCHOR.TOP, "center": MSO_ANCHOR.MIDDLE, "bottom": MSO_ANCHOR.BOTTOM}
    if properties.get("vertical_alignment") in anchors:
        cell.vertical_anchor = anchors[properties["vertical_alignment"]]
    fill = properties.get("fill")
    if fill == "none":
        cell.fill.background()
    elif fill:
        cell.fill.solid()
        canonical = properties.get("fill_color")
        # Editing the canonical legacy fill string must not be shadowed by its old color snapshot.
        from textalchemy.core.color import ColorValue

        if canonical and ColorValue.from_dict(canonical).to_hex() != fill:
            canonical = None
        set_color(cell.fill.fore_color, canonical or fill, report, location)
    tcpr = cell._tc.get_or_add_tcPr()
    for tag, border in properties.get("pptx_borders", {}).items():
        if tag not in ("lnL", "lnR", "lnT", "lnB", "lnTlToBr", "lnBlToTr"):
            report.add(IssueSeverity.LOSS, "tables", "Неизвестная граница ячейки не перенесена.", location)
            continue
        old = tcpr.find(A + tag)
        if old is not None:
            tcpr.remove(old)
        line = OxmlElement("a:" + tag)
        line.set("w", str(int(Pt(border.get("width_pt", 1)))))
        if border.get("none"):
            etree.SubElement(line, A + "noFill")
        elif border.get("color"):
            solid = OxmlElement("a:solidFill")
            line.append(solid)
            set_color(ColorFormat.from_colorchoice_parent(solid), border["color"], report, location)
        if border.get("dash"):
            etree.SubElement(line, A + "prstDash", val=border["dash"])
        tcpr.insert(0, line)
    order = {
        name: index
        for index, name in enumerate(
            (
                "lnL",
                "lnR",
                "lnT",
                "lnB",
                "lnTlToBr",
                "lnBlToTr",
                "cell3D",
                "noFill",
                "solidFill",
                "gradFill",
                "blipFill",
                "pattFill",
                "grpFill",
                "headers",
                "extLst",
            )
        )
    }
    tcpr[:] = sorted(tcpr, key=lambda node: order.get(node.tag.removeprefix(A), 99))
