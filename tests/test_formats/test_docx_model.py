"""Интеграционные тесты DOCX → DocumentModel."""

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.shared import Inches, Pt
from PIL import Image as PillowImage

from textalchemy.core.document_model import Formula, Image, Paragraph, ResourceKind, Table
from textalchemy.formats.docx import read_docx_model


def test_read_docx_model_preserves_order_styles_tables_and_metadata(tmp_path):
    path = tmp_path / "structured.docx"
    source = Document()
    source.core_properties.title = "Structured document"
    paragraph = source.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run("Formatted")
    run.bold = True
    run.italic = True
    run.font.name = "Arial"
    run.font.size = Pt(14)
    table = source.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "left"
    table.cell(0, 1).text = "right"
    source.add_paragraph("After table")
    source.save(path)

    model = read_docx_model(path)

    assert model.metadata["title"] == "Structured document"
    assert model.source_format == "docx"
    assert [type(block) for block in model.sections[0].blocks] == [Paragraph, Table, Paragraph]
    imported = model.sections[0].blocks[0]
    assert isinstance(imported, Paragraph)
    assert imported.alignment == "center"
    assert imported.content[0].style.bold is True
    assert imported.content[0].style.italic is True
    assert imported.content[0].style.font_family == "Arial"
    assert imported.content[0].style.font_size.pt == 14


def test_read_docx_model_extracts_image_formula_header_and_page_geometry(tmp_path):
    path = tmp_path / "media.docx"
    image_path = tmp_path / "pixel.png"
    PillowImage.new("RGB", (8, 6), "red").save(image_path)

    source = Document()
    source.sections[0].header.paragraphs[0].text = "Header text"
    source.sections[0].page_width = Inches(9)
    paragraph = source.add_paragraph("Before ")
    picture = paragraph.add_run()
    picture.add_picture(str(image_path), width=Inches(1))
    math = OxmlElement("m:oMath")
    math_run = OxmlElement("m:r")
    math_text = OxmlElement("m:t")
    math_text.text = "x+1"
    math_run.append(math_text)
    math.append(math_run)
    paragraph._p.append(math)
    source.save(path)

    model = read_docx_model(path)

    imported = model.sections[0].blocks[0]
    assert isinstance(imported, Paragraph)
    assert any(isinstance(item, Image) for item in imported.content)
    assert any(isinstance(item, Formula) and item.fallback_text == "x+1" for item in imported.content)
    image_resources = [resource for resource in model.resources.values() if resource.kind is ResourceKind.RASTER_IMAGE]
    assert len(image_resources) == 1
    resource = image_resources[0]
    assert resource.kind is ResourceKind.RASTER_IMAGE
    assert resource.media_type == "image/png"
    assert resource.data
    assert model.sections[0].headers[0].plain_text == "Header text"
    assert model.sections[0].page.width.pt == 648
    assert model.validate() == []


def test_read_docx_model_preserves_horizontal_cell_merge(tmp_path):
    path = tmp_path / "merged.docx"
    source = Document()
    table = source.add_table(rows=1, cols=3)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "merged"
    table.cell(0, 2).text = "single"
    source.save(path)

    model = read_docx_model(path)

    imported = model.sections[0].blocks[0]
    assert isinstance(imported, Table)
    assert len(imported.rows[0].cells) == 2
    assert imported.rows[0].cells[0].column_span == 2
    assert imported.rows[0].cells[0].blocks[0].plain_text == "merged"


def test_read_docx_model_resolves_style_inheritance_for_paragraphs_and_runs(tmp_path):
    path = tmp_path / "inherited-styles.docx"
    source = Document()
    base = source.styles.add_style("Scientific Base", WD_STYLE_TYPE.PARAGRAPH)
    base.font.name = "Arial"
    base.font.size = Pt(12)
    base.font.bold = True
    base.paragraph_format.space_after = Pt(9)
    child = source.styles.add_style("Scientific Result", WD_STYLE_TYPE.PARAGRAPH)
    child.base_style = base
    child.font.color.rgb = source.styles["Heading 1"].font.color.rgb
    emphasis = source.styles.add_style("Scientific Emphasis", WD_STYLE_TYPE.CHARACTER)
    emphasis.font.italic = True
    paragraph = source.add_paragraph(style=child)
    run = paragraph.add_run("Inherited formatting")
    run.style = emphasis
    source.save(path)

    model = read_docx_model(path)

    result_style = next(style for style in model.styles.values() if style.properties["style_name"] == "Scientific Result")
    assert result_style.font_family == "Arial"
    assert result_style.font_size.pt == 12
    assert result_style.bold is True
    assert result_style.properties["space_after_pt"] == 9
    imported = model.sections[0].blocks[0]
    assert isinstance(imported, Paragraph)
    assert imported.properties["space_after_pt"] == 9
    assert imported.content[0].style.font_family == "Arial"
    assert imported.content[0].style.font_size.pt == 12
    assert imported.content[0].style.bold is True
    assert imported.content[0].style.italic is True
    assert imported.content[0].style.properties["direct_fields"] == []


def test_read_docx_model_preserves_continuous_section_and_header_linkage(tmp_path):
    path = tmp_path / "sections.docx"
    source = Document()
    source.sections[0].header.paragraphs[0].text = "Shared header"
    source.add_paragraph("First section")
    second = source.add_section(WD_SECTION.CONTINUOUS)
    second.header.is_linked_to_previous = True
    second.footer.is_linked_to_previous = True
    second.header_distance = Inches(0.35)
    second.footer_distance = Inches(0.4)
    source.add_paragraph("Second section")
    source.save(path)

    model = read_docx_model(path)

    assert len(model.sections) == 2
    assert model.sections[1].properties["start_type"] == "CONTINUOUS"
    assert model.sections[1].properties["header_linked_to_previous"] is True
    assert model.sections[1].properties["footer_linked_to_previous"] is True
    assert model.sections[1].properties["header_distance_pt"] == 25.2
    assert model.sections[1].properties["footer_distance_pt"] == 28.8


def test_read_docx_model_preserves_first_and_even_running_content(tmp_path):
    path = tmp_path / "alternate-running-content.docx"
    source = Document()
    section = source.sections[0]
    source.settings.odd_and_even_pages_header_footer = True
    section.different_first_page_header_footer = True
    section.header.paragraphs[0].text = "Odd header"
    section.footer.paragraphs[0].text = "Odd footer"
    section.first_page_header.paragraphs[0].text = "First header"
    section.first_page_footer.paragraphs[0].text = "First footer"
    section.even_page_header.paragraphs[0].text = "Even header"
    section.even_page_footer.paragraphs[0].text = "Even footer"
    source.add_paragraph("Body")
    source.save(path)

    model = read_docx_model(path)
    imported = model.sections[0]

    assert imported.properties["different_first_page_header_footer"] is True
    assert imported.properties["odd_and_even_pages_header_footer"] is True
    assert imported.headers[0].plain_text == "Odd header"
    assert imported.footers[0].plain_text == "Odd footer"
    assert imported.first_page_headers[0].plain_text == "First header"
    assert imported.first_page_footers[0].plain_text == "First footer"
    assert imported.even_page_headers[0].plain_text == "Even header"
    assert imported.even_page_footers[0].plain_text == "Even footer"
