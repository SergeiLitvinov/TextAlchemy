"""Own DOCX table fixture; native XML construction is confined to independent QA."""

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt


def write_percentage_table(path):
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(1.5)
    section.left_margin = section.right_margin = Cm(2)
    normal = document.styles["Normal"]
    normal.font.name, normal.font.size = "Arial", Pt(11)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = 1
    document.add_paragraph("Own table width acceptance")
    table = document.add_table(rows=20, cols=3)
    table.autofit = False
    total_width = table._tbl.tblPr.find(qn("w:tblW"))
    total_width.set(qn("w:type"), "dxa")
    total_width.set(qn("w:w"), str(Cm(17).twips))
    for column, width in zip(table.columns, (Cm(1.7), Cm(13.6), Cm(1.7)), strict=True):
        column.width = width
    own_text = " ".join(["Own table text verifies column widths through two cycles"] * 2)
    for index, row in enumerate(table.rows, 1):
        for cell, text, fraction in zip(row.cells,
                                        (str(index), own_text, "8"),
                                        (500, 4000, 500), strict=True):
            cell.text = text
            width = cell._tc.get_or_add_tcPr().get_or_add_tcW()
            width.set(qn("w:type"), "pct")
            width.set(qn("w:w"), str(fraction))
    document.save(path)


def write_smart_tag(path):
    """Place own text inside the legacy native smartTag wrapper, without scripts."""
    document = Document()
    paragraph = document.add_paragraph("Before ")
    tag = OxmlElement("w:smartTag")
    tag.set(qn("w:uri"), "urn:textalchemy:own-acceptance")
    tag.set(qn("w:element"), "OwnToken")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "OwnSmartToken"
    run.append(text)
    tag.append(run)
    paragraph._p.append(tag)
    paragraph.add_run(" After")
    document.save(path)
