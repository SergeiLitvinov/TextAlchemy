"""Построитель сложного научного DOCX без хранения бинарника в Git."""

from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw

FIXED_ZIP_TIME = (2024, 1, 1, 0, 0, 0)
SVG_BYTES = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="180" viewBox="0 0 640 180">'
    b'<rect width="640" height="180" fill="#f2f4f7"/>'
    b'<path d="M45 135 C150 20 255 160 365 55 S535 70 595 30" fill="none" '
    b'stroke="#2e74b5" stroke-width="8"/>'
    b'<circle cx="365" cy="55" r="11" fill="#c44e52"/>'
    b'<text x="45" y="165" font-family="Arial" font-size="18">Vector response curve</text></svg>'
)


def build_scientific_report(path: str | Path) -> Path:
    """Создать стабильный DOCX, покрывающий важные элементы конвертации."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    chart = output.parent / "_scientific_report_chart.png"
    vector_placeholder = output.parent / "_scientific_report_vector_placeholder.png"
    _build_chart(chart)
    _build_vector_placeholder(vector_placeholder)

    document = Document()
    _set_metadata(document)
    _set_styles(document)
    section = document.sections[0]
    _set_portrait_page(section)
    _set_header_footer(document, section)
    _add_title(document)
    _add_summary(document)
    _add_numbered_methods(document)
    _add_formula(document)
    _add_table(document)
    _add_figures(document, chart, vector_placeholder)
    _add_footnote_reference(document)

    landscape = document.add_section(WD_SECTION.NEW_PAGE)
    landscape.orientation = WD_ORIENT.LANDSCAPE
    landscape.page_width, landscape.page_height = Inches(11), Inches(8.5)
    landscape.left_margin = landscape.right_margin = Inches(0.75)
    landscape.top_margin = landscape.bottom_margin = Inches(0.75)
    landscape.header_distance = landscape.footer_distance = Inches(0.35)
    landscape.different_first_page_header_footer = False
    landscape.header.is_linked_to_previous = True
    landscape.footer.is_linked_to_previous = True
    document.add_heading("Appendix A. Wide observations", level=1)
    _add_wide_table(document)
    document.add_paragraph(
        "The landscape section verifies section breaks, explicit page geometry, "
        "repeated table headers, and long scientific labels."
    )

    document.save(output)
    chart.unlink()
    vector_placeholder.unlink()
    _patch_vector_and_footnote(output)
    _normalise_archive(output)
    return output


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _set_metadata(document: Document) -> None:
    props = document.core_properties
    props.title = "TextAlchemy scientific conversion corpus"
    props.subject = "Document fidelity fixture"
    props.author = "TextAlchemy"
    props.keywords = "conversion, formula, vector, table, footnote"
    props.comments = "Generated reproducibly by tests.corpus.scientific_report"
    fixed = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    props.created = fixed
    props.modified = fixed


def _set_styles(document: Document) -> None:
    styles = document.styles
    normal = styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.1
    for style_name, size, before, after in (("Heading 1", 16, 16, 8), ("Heading 2", 13, 12, 6)):
        style = styles[style_name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor(0x2E, 0x74, 0xB5)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
    caption = styles.add_style("Corpus Caption", WD_STYLE_TYPE.PARAGRAPH)
    caption.font.name = "Calibri"
    caption.font.size = Pt(9)
    caption.font.italic = True
    caption.paragraph_format.space_after = Pt(8)
    footnote_reference = styles.add_style("Footnote Reference", WD_STYLE_TYPE.CHARACTER)
    footnote_reference.font.superscript = True
    footnote_text = styles.add_style("Footnote Text", WD_STYLE_TYPE.PARAGRAPH)
    footnote_text.font.name = "Calibri"
    footnote_text.font.size = Pt(9)
    footnote_text.paragraph_format.space_after = Pt(0)
    endnote_reference = styles.add_style("Endnote Reference", WD_STYLE_TYPE.CHARACTER)
    endnote_reference.font.superscript = True
    endnote_text = styles.add_style("Endnote Text", WD_STYLE_TYPE.PARAGRAPH)
    endnote_text.font.name = "Calibri"
    endnote_text.font.size = Pt(9)
    endnote_text.paragraph_format.space_after = Pt(0)
    table_style = styles.add_style("Corpus Scientific Table", WD_STYLE_TYPE.TABLE)
    table_style.base_style = styles["Table Grid"]


def _set_portrait_page(section) -> None:
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = section.bottom_margin = Inches(1)
    section.left_margin = section.right_margin = Inches(1)
    section.header_distance = section.footer_distance = Inches(0.492)


def _set_header_footer(document: Document, section) -> None:
    document.settings.odd_and_even_pages_header_footer = True
    section.different_first_page_header_footer = True
    header = section.header.paragraphs[0]
    header.text = "TEXTALCHEMY  /  ODD PAGE"
    header.style = "Caption"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    first_header = section.first_page_header.paragraphs[0]
    first_header.text = "TEXTALCHEMY  /  FIRST PAGE"
    first_header.style = "Caption"
    first_header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    even_header = section.even_page_header.paragraphs[0]
    even_header.text = "TEXTALCHEMY  /  EVEN PAGE"
    even_header.style = "Caption"
    even_header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _set_page_footer(section.footer.paragraphs[0], "TextAlchemy odd-page corpus")
    _set_page_footer(section.first_page_footer.paragraphs[0], "TextAlchemy first-page corpus")
    _set_page_footer(section.even_page_footer.paragraphs[0], "TextAlchemy even-page corpus")


def _set_page_footer(footer, label: str) -> None:
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run(f"{label}  •  ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    footer.add_run(" / ")
    _append_complex_field(footer, "NUMPAGES", "3")


def _add_title(document: Document) -> None:
    eyebrow = document.add_paragraph()
    eyebrow.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = eyebrow.add_run("REPRODUCIBLE SCIENTIFIC REPORT")
    run.bold = True
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(5)
    run = title.add_run("Preservation of Scientific Content Across Formats")
    run.bold = True
    run.font.size = Pt(22)
    run.font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)
    meta = document.add_paragraph("Research note TA-2024-01  |  1 January 2024  |  Quality Engineering")
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.paragraph_format.space_after = Pt(16)


def _add_summary(document: Document) -> None:
    document.add_heading("Executive summary", level=1)
    paragraph = document.add_paragraph()
    paragraph.add_run("Objective. ").bold = True
    paragraph.add_run(
        "Measure how reliably a conversion pipeline retains editable text, typography, page geometry, "
        "images, formulas, and tables. "
    )
    _add_hyperlink(paragraph, "Open conversion specification", "https://example.org/textalchemy/spec")
    paragraph.add_run(" for the stable evaluation criteria. ")
    _add_internal_hyperlink(paragraph, "Jump to the quality model", "quality_model")
    paragraph.add_run(".")
    note = document.add_paragraph()
    note.paragraph_format.left_indent = Inches(0.25)
    note.paragraph_format.right_indent = Inches(0.25)
    run = note.add_run("Key finding: structure must be measured independently from visual similarity.")
    run.bold = True
    run.font.color.rgb = RGBColor(0x2E, 0x74, 0xB5)


def _add_numbered_methods(document: Document) -> None:
    document.add_heading("Method", level=1)
    document.add_paragraph("The corpus uses three complementary checks:")
    for text in (
        "Inspect semantic elements and embedded resources.",
        "Compare page geometry and element-retention ratios.",
        "Render every page and verify stable visual occupancy.",
    ):
        document.add_paragraph(text, style="List Number")


def _add_formula(document: Document) -> None:
    heading = document.add_heading("Quality model", level=2)
    _add_bookmark(heading, "quality_model", 42)
    paragraph = document.add_paragraph("The weighted fidelity score is ")
    math = OxmlElement("m:oMath")
    math_run = OxmlElement("m:r")
    math_text = OxmlElement("m:t")
    math_text.text = "Q = 0.4S + 0.35V + 0.25E"
    math_run.append(math_text)
    math.append(math_run)
    paragraph._p.append(math)
    paragraph.add_run(", where S is structure, V is visual similarity, and E is editability.")


def _add_table(document: Document) -> None:
    document.add_heading("Measured signals", level=2)
    table = document.add_table(rows=4, cols=4)
    table.style = "Corpus Scientific Table"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    widths = (2.15, 1.25, 1.25, 1.85)
    headings = ("Signal", "Source", "Target", "Acceptance")
    for index, text in enumerate(headings):
        cell = table.cell(0, index)
        cell.text = text
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        _shade_cell(cell, "F2F4F7")
        for run in cell.paragraphs[0].runs:
            run.bold = True
    values = (
        ("Characters", "1,024", "1,021", "≥ 99%"),
        ("Embedded resources", "2", "2", "exact hashes"),
        ("Page geometry", "Letter", "Letter", "± 0.5 pt"),
    )
    for row_index, row in enumerate(values, 1):
        for col_index, text in enumerate(row):
            table.cell(row_index, col_index).text = text
    table.cell(3, 0).merge(table.cell(3, 1)).text = "Page geometry (merged label)"
    for row in table.rows:
        for index, cell in enumerate(row.cells):
            cell.width = Inches(widths[index])
            _set_cell_margins(cell, top=80, start=120, bottom=80, end=120)
    document.add_paragraph("Table 1. Structural and geometric acceptance criteria.", style="Corpus Caption")


def _add_figures(document: Document, chart: Path, vector_placeholder: Path) -> None:
    document.add_heading("Figures", level=2)
    paragraph = document.add_paragraph()
    shape = paragraph.add_run().add_picture(str(chart), width=Inches(3.15))
    shape._inline.docPr.set("descr", "Raster chart with three quality series")
    _apply_crop_and_rotation(shape._inline)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.keep_with_next = True
    document.add_paragraph("Figure 1. Raster control chart.", style="Corpus Caption").alignment = WD_ALIGN_PARAGRAPH.CENTER

    paragraph = document.add_paragraph()
    shape = paragraph.add_run().add_picture(str(vector_placeholder), width=Inches(4.6), height=Inches(1.3))
    shape._inline.docPr.set("descr", "Vector response curve")
    shape._inline.docPr.set("title", "CORPUS_VECTOR_PLACEHOLDER")
    _make_floating_anchor(shape._inline)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.line_spacing = Inches(1.3)
    document.add_paragraph("Figure 2. SVG vector control curve.", style="Corpus Caption").alignment = WD_ALIGN_PARAGRAPH.CENTER


def _add_footnote_reference(document: Document) -> None:
    paragraph = document.add_paragraph("A portable fallback is required for every mathematical expression")
    run = paragraph.add_run()
    run_properties = run._r.get_or_add_rPr()
    style = OxmlElement("w:rStyle")
    style.set(qn("w:val"), "FootnoteReference")
    run_properties.append(style)
    reference = OxmlElement("w:footnoteReference")
    reference.set(qn("w:id"), "1")
    run._r.append(reference)
    paragraph.add_run(" so plain-text targets remain understandable.")
    paragraph.add_run(" Related note plumbing is verified")
    endnote_run = paragraph.add_run()
    endnote_properties = endnote_run._r.get_or_add_rPr()
    endnote_style = OxmlElement("w:rStyle")
    endnote_style.set(qn("w:val"), "EndnoteReference")
    endnote_properties.append(endnote_style)
    endnote_reference = OxmlElement("w:endnoteReference")
    endnote_reference.set(qn("w:id"), "1")
    endnote_run._r.append(endnote_reference)
    paragraph.add_run(".")


def _add_wide_table(document: Document) -> None:
    table = document.add_table(rows=5, cols=6)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    headings = ("Variant", "Text", "Styles", "Images", "Formula", "Geometry")
    for index, heading in enumerate(headings):
        table.cell(0, index).text = heading
        _shade_cell(table.cell(0, index), "D9EAF7")
        for run in table.cell(0, index).paragraphs[0].runs:
            run.bold = True
    for row_index in range(1, 5):
        values = (f"Pipeline {row_index}", "99.7%", "98.9%", "100%", "native", f"± {row_index / 10:.1f} pt")
        for col_index, value in enumerate(values):
            table.cell(row_index, col_index).text = value


def _build_chart(path: Path) -> None:
    image = Image.new("RGB", (720, 320), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((55, 25, 690, 270), fill="#f8fafc", outline="#9aa6b2", width=2)
    for y in (75, 125, 175, 225):
        draw.line((55, y, 690, y), fill="#d8dee5", width=1)
    series = (
        ("#2e74b5", (235, 190, 145, 95, 68)),
        ("#55a868", (248, 215, 180, 135, 105)),
        ("#c44e52", (260, 240, 220, 195, 165)),
    )
    xs = (75, 220, 365, 510, 655)
    for colour, ys in series:
        points = list(zip(xs, ys, strict=True))
        draw.line(points, fill=colour, width=5)
        for x, y in points:
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=colour)
    draw.text((55, 285), "structure                 visual fidelity                 editability", fill="#333333")
    image.save(path, format="PNG", optimize=False, compress_level=9)


def _build_vector_placeholder(path: Path) -> None:
    image = Image.new("RGB", (640, 180), "#f2f4f7")
    draw = ImageDraw.Draw(image)
    draw.line((45, 135, 170, 35, 365, 55, 595, 30), fill="#2e74b5", width=8)
    draw.ellipse((354, 44, 376, 66), fill="#c44e52")
    image.save(path, format="PNG", optimize=False, compress_level=9)


def _make_floating_anchor(inline) -> None:
    inline.tag = qn("wp:anchor")
    for name, value in (
        ("distT", "0"),
        ("distB", "0"),
        ("distL", "0"),
        ("distR", "0"),
        ("simplePos", "0"),
        ("relativeHeight", "4"),
        ("behindDoc", "0"),
        ("locked", "0"),
        ("layoutInCell", "1"),
        ("allowOverlap", "0"),
    ):
        inline.set(name, value)
    simple_position = OxmlElement("wp:simplePos")
    simple_position.set("x", "0")
    simple_position.set("y", "0")
    horizontal = OxmlElement("wp:positionH")
    horizontal.set("relativeFrom", "column")
    align = OxmlElement("wp:align")
    align.text = "center"
    horizontal.append(align)
    vertical = OxmlElement("wp:positionV")
    vertical.set("relativeFrom", "paragraph")
    offset = OxmlElement("wp:posOffset")
    offset.text = "0"
    vertical.append(offset)
    inline.insert(0, simple_position)
    inline.insert(1, horizontal)
    inline.insert(2, vertical)
    wrap = OxmlElement("wp:wrapTight")
    wrap.set("wrapText", "bothSides")
    polygon = OxmlElement("wp:wrapPolygon")
    polygon.set("edited", "1")
    for index, (x, y) in enumerate(((0, 0), (18400, 900), (21600, 17800), (2600, 21600))):
        point = OxmlElement("wp:start" if index == 0 else "wp:lineTo")
        point.set("x", str(x))
        point.set("y", str(y))
        polygon.append(point)
    wrap.append(polygon)
    inline.insert(inline.index(inline.docPr), wrap)


def _apply_crop_and_rotation(inline) -> None:
    fills = inline.xpath(".//pic:blipFill")
    source = OxmlElement("a:srcRect")
    for name, value in (("l", "3000"), ("t", "2000"), ("r", "4000"), ("b", "1000")):
        source.set(name, value)
    blip = fills[0].xpath("./a:blip")[0]
    fills[0].insert(fills[0].index(blip) + 1, source)
    inline.xpath(".//pic:spPr/a:xfrm")[0].set("rot", "180000")


def _add_hyperlink(paragraph, text: str, url: str) -> None:
    from docx.opc.constants import RELATIONSHIP_TYPE

    relationship_id = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    colour = OxmlElement("w:color")
    colour.set(qn("w:val"), "0563C1")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    properties.extend((colour, underline))
    run.append(properties)
    node = OxmlElement("w:t")
    node.text = text
    run.append(node)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _add_internal_hyperlink(paragraph, text: str, anchor: str) -> None:
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("w:anchor"), anchor)
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    colour = OxmlElement("w:color")
    colour.set(qn("w:val"), "0563C1")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    properties.extend((colour, underline))
    run.append(properties)
    node = OxmlElement("w:t")
    node.text = text
    run.append(node)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _add_bookmark(paragraph, name: str, bookmark_id: int) -> None:
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bookmark_id))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bookmark_id))
    paragraph._p.insert(0, start)
    paragraph._p.append(end)


def _append_complex_field(paragraph, instruction: str, cached_result: str) -> None:
    begin_run = OxmlElement("w:r")
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin_run.append(begin)
    instruction_run = OxmlElement("w:r")
    instruction_text = OxmlElement("w:instrText")
    instruction_text.set(qn("xml:space"), "preserve")
    instruction_text.text = f" {instruction} "
    instruction_run.append(instruction_text)
    separate_run = OxmlElement("w:r")
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    separate_run.append(separate)
    result_run = OxmlElement("w:r")
    result_text = OxmlElement("w:t")
    result_text.text = cached_result
    result_run.append(result_text)
    end_run = OxmlElement("w:r")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    end_run.append(end)
    paragraph._p.extend((begin_run, instruction_run, separate_run, result_run, end_run))


def _shade_cell(cell, fill: str) -> None:
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shading)


def _set_cell_margins(cell, **kwargs: int) -> None:
    properties = cell._tc.get_or_add_tcPr()
    margins = properties.first_child_found_in("w:tcMar")
    if margins is None:
        margins = OxmlElement("w:tcMar")
        properties.append(margins)
    for edge in ("top", "start", "bottom", "end"):
        if edge not in kwargs:
            continue
        node = margins.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            margins.append(node)
        node.set(qn("w:w"), str(kwargs[edge]))
        node.set(qn("w:type"), "dxa")


def _patch_vector_and_footnote(path: Path) -> None:
    entries = _read_archive(path)
    document_xml = entries["word/document.xml"].decode("utf-8")
    relationships = entries["word/_rels/document.xml.rels"].decode("utf-8")
    content_types = entries["[Content_Types].xml"].decode("utf-8")

    marker = 'title="CORPUS_VECTOR_PLACEHOLDER"'
    marker_index = document_xml.index(marker)
    blip_index = document_xml.index("r:embed=", marker_index)
    quote = document_xml[blip_index + len("r:embed=")]
    start = blip_index + len("r:embed=") + 1
    end = document_xml.index(quote, start)
    relationship_id = document_xml[start:end]
    target_marker = f'Id="{relationship_id}"'
    relationship_index = relationships.index(target_marker)
    target_index = relationships.index('Target="', relationship_index) + len('Target="')
    target_end = relationships.index('"', target_index)
    old_target = relationships[target_index:target_end]
    relationships = relationships[:target_index] + "media/vector-curve.svg" + relationships[target_end:]
    entries.pop(f"word/{old_target}", None)
    entries["word/media/vector-curve.svg"] = SVG_BYTES

    if 'Extension="svg"' not in content_types:
        content_types = content_types.replace(
            "</Types>", '<Default Extension="svg" ContentType="image/svg+xml"/></Types>'
        )
    if 'PartName="/word/footnotes.xml"' not in content_types:
        content_types = content_types.replace(
            "</Types>",
            '<Override PartName="/word/footnotes.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/></Types>',
        )
    if 'PartName="/word/endnotes.xml"' not in content_types:
        content_types = content_types.replace(
            "</Types>",
            '<Override PartName="/word/endnotes.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"/></Types>',
        )
    if "relationships/footnotes" not in relationships:
        relationships = relationships.replace(
            "</Relationships>",
            '<Relationship Id="rIdCorpusFootnotes" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" '
            'Target="footnotes.xml"/></Relationships>',
        )
    if "relationships/endnotes" not in relationships:
        relationships = relationships.replace(
            "</Relationships>",
            '<Relationship Id="rIdCorpusEndnotes" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes" '
            'Target="endnotes.xml"/></Relationships>',
        )
    entries["word/footnotes.xml"] = _footnotes_xml()
    entries["word/_rels/footnotes.xml.rels"] = _footnote_relationships_xml()
    entries["word/media/footnote-icon.png"] = _note_icon_bytes()
    entries["word/endnotes.xml"] = _endnotes_xml()
    entries["word/_rels/endnotes.xml.rels"] = _endnote_relationships_xml()
    entries["word/document.xml"] = document_xml.encode("utf-8")
    entries["word/_rels/document.xml.rels"] = relationships.encode("utf-8")
    entries["[Content_Types].xml"] = content_types.encode("utf-8")
    _write_archive(path, entries)


def _footnotes_xml() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        b'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        b'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        b'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        b'<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
        b'<w:footnote w:type="continuationSeparator" w:id="0">'
        b'<w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
        b'<w:footnote w:id="1"><w:p><w:pPr><w:pStyle w:val="FootnoteText"/></w:pPr>'
        b'<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr><w:footnoteRef/></w:r><w:r>'
        b'<w:t xml:space="preserve"> Portable fallback text is part of the </w:t></w:r>'
        b'<w:hyperlink r:id="rIdNoteLink"><w:r><w:rPr><w:color w:val="2E74B5"/><w:u w:val="single"/>'
        b'</w:rPr>'
        b'<w:t>conversion contract</w:t></w:r></w:hyperlink><w:r><w:t xml:space="preserve">. </w:t>'
        b'<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
        b'<wp:extent cx="152400" cy="152400"/><wp:docPr id="9001" name="Footnote icon" '
        b'descr="Footnote relationship image"/><wp:cNvGraphicFramePr>'
        b'<a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr><a:graphic>'
        b'<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
        b'<pic:nvPicPr><pic:cNvPr id="0" name="footnote-icon.png"/><pic:cNvPicPr/></pic:nvPicPr>'
        b'<pic:blipFill><a:blip r:embed="rIdNoteImage"/><a:stretch><a:fillRect/></a:stretch>'
        b'</pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="152400" cy="152400"/>'
        b'</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        b'</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p></w:footnote></w:footnotes>'
    )


def _footnote_relationships_xml() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rIdNoteImage" '
        b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        b'Target="media/footnote-icon.png"/>'
        b'<Relationship Id="rIdNoteLink" '
        b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        b'Target="https://example.com/conversion-contract" TargetMode="External"/>'
        b'</Relationships>'
    )


def _endnotes_xml() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<w:endnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        b'<w:endnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:endnote>'
        b'<w:endnote w:type="continuationSeparator" w:id="0">'
        b'<w:p><w:r><w:continuationSeparator/></w:r></w:p></w:endnote>'
        b'<w:endnote w:id="1"><w:p><w:pPr><w:pStyle w:val="EndnoteText"/></w:pPr>'
        b'<w:r><w:rPr><w:rStyle w:val="EndnoteReference"/></w:rPr><w:endnoteRef/></w:r>'
        b'<w:r><w:t xml:space="preserve"> Note relationships retain an </w:t></w:r>'
        b'<w:hyperlink r:id="rIdEndnoteLink"><w:r><w:rPr><w:color w:val="2E74B5"/>'
        b'<w:u w:val="single"/></w:rPr><w:t>external target</w:t></w:r></w:hyperlink>'
        b'<w:r><w:t>.</w:t></w:r></w:p></w:endnote></w:endnotes>'
    )


def _endnote_relationships_xml() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rIdEndnoteLink" '
        b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        b'Target="https://example.com/endnote-target" TargetMode="External"/>'
        b'</Relationships>'
    )


def _note_icon_bytes() -> bytes:
    image = Image.new("RGB", (24, 24), "#2E74B5")
    draw = ImageDraw.Draw(image)
    draw.ellipse((6, 6, 18, 18), fill="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return buffer.getvalue()


def _normalise_archive(path: Path) -> None:
    _write_archive(path, _read_archive(path))


def _read_archive(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _write_archive(path: Path, entries: dict[str, bytes]) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, entries[name])
    path.write_bytes(buffer.getvalue())


__all__ = ["build_scientific_report", "sha256"]


if __name__ == "__main__":
    result = build_scientific_report(Path("tmp/corpus/scientific-report.docx"))
    print(result)
