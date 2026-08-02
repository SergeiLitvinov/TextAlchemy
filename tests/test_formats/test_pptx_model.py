"""Интеграционные тесты PPTX → DocumentModel (импортёр на общей модели)."""

from pathlib import Path

import pytest
from lxml import etree
from PIL import Image as PillowImage
from pptx import Presentation
from pptx.chart.data import ChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Inches, Pt

from textalchemy.core.document_model import Formula, Image, Paragraph, ResourceKind, Table
from textalchemy.formats.pptx import read_pptx, read_pptx_model

CORPUS_PPTX = Path(__file__).resolve().parent.parent / "corpus" / "office" / "libreoffice-scientific-slides.pptx"


def _png_bytes(tmp_path: Path) -> bytes:
    path = tmp_path / "_probe.png"
    PillowImage.new("RGB", (12, 8), "green").save(path)
    return path.read_bytes()


def _build_rich_pptx(path: Path, *, image_bytes: bytes | None = None) -> None:
    """Собрать PPTX с текстом, фигурами, группой, формулой, таблицей, диаграммой."""
    presentation = Presentation()
    presentation.slide_width = Inches(13.333333)
    presentation.slide_height = Inches(7.5)
    presentation.core_properties.title = "Rich deck"

    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor(0xF2, 0xF2, 0xF2)

    box = slide.shapes.add_textbox(Inches(1), Inches(0.5), Inches(6), Inches(0.6))
    first = box.text_frame.paragraphs[0]
    run = first.add_run()
    run.text = "Mixed formatting "
    run.font.bold = True
    run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(0xAA, 0x00, 0x00)
    link_run = first.add_run()
    link_run.text = "and link"
    link_run.font.italic = True
    link_run.hyperlink.address = "https://example.com"

    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1), Inches(1.4), Inches(3), Inches(0.8))
    shape.text = "Filled shape"
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(0x5B, 0x9B, 0xD5)

    group = slide.shapes.add_group_shape()
    group.left = Emu(457200)
    group.top = Emu(457200)
    group.width = Emu(1828800)
    group.height = Emu(914400)
    group.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(457200), Emu(457200), Emu(914400), Emu(457200)).text = "in group"

    math_box = slide.shapes.add_textbox(Inches(7), Inches(0.5), Inches(4), Inches(0.6))
    omath = etree.fromstring(
        b'<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        b"<m:r><m:t>x</m:t></m:r>"
        b"<m:sSup>"
        b"<m:e><m:r><m:t>y</m:t></m:r></m:e>"
        b"<m:sup><m:r><m:t>2</m:t></m:r></m:sup>"
        b"</m:sSup></m:oMath>"
    )
    math_box.text_frame.paragraphs[0]._p.append(omath)

    table = slide.shapes.add_table(2, 2, Inches(1), Inches(2.6), Inches(4), Inches(1.2)).table
    table.cell(0, 0).text = "A1"
    table.cell(0, 1).text = "B1"
    table.cell(1, 0).text = "A2"
    table.cell(1, 1).text = "B2"

    chart_data = ChartData()
    chart_data.categories = ["Alpha", "Beta"]
    chart_data.add_series("Score", (10, 20))
    slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(6), Inches(2.6), Inches(5), Inches(3), chart_data)

    slide.notes_slide.notes_text_frame.text = "Speaker notes for test."

    if image_bytes is not None:
        image_path = path.parent / "_probe_pic.png"
        image_path.write_bytes(image_bytes)
        slide.shapes.add_picture(str(image_path), Inches(1), Inches(4), Inches(2), Inches(1))
        image_path.unlink(missing_ok=True)

    presentation.save(path)


def _paragraphs(blocks):
    return [block for block in blocks if isinstance(block, Paragraph)]


class TestReadPptxModel:
    def test_builds_sections_metadata_and_blocks(self, tmp_path):
        path = tmp_path / "rich.pptx"
        _build_rich_pptx(path)

        model = read_pptx_model(path)

        assert model.source_format == "pptx"
        assert len(model.sections) == 1
        assert model.metadata["title"] == "Rich deck"
        assert model.metadata["slide_width_pt"] == pytest.approx(13.333333 * 72, abs=1.0)
        assert model.validate() == []

    def test_preserves_run_formatting_and_hyperlink(self, tmp_path):
        path = tmp_path / "rich.pptx"
        _build_rich_pptx(path)

        model = read_pptx_model(path)
        paragraphs = _paragraphs(model.sections[0].blocks)
        text_box = next(p for p in paragraphs if any(run.text.startswith("Mixed") for run in p.content))
        runs = [run for run in text_box.content if run.text.strip()]

        assert runs[0].style.bold is True
        assert runs[0].style.font_size.pt == 20
        assert runs[0].style.color == "#AA0000"
        assert runs[1].style.italic is True
        assert runs[1].link == "https://example.com"

    def test_keeps_shape_geometry_and_fill(self, tmp_path):
        path = tmp_path / "rich.pptx"
        _build_rich_pptx(path)

        model = read_pptx_model(path)
        shape_block = next(
            p for p in _paragraphs(model.sections[0].blocks) if p.properties["pptx"]["shape"].get("prst") == "roundRect"
        )
        assert shape_block.box.x == pytest.approx(72.0)
        assert shape_block.properties["pptx"]["shape"]["fill"] == "#5B9BD5"

    def test_group_child_resolves_absolute_geometry(self, tmp_path):
        path = tmp_path / "rich.pptx"
        _build_rich_pptx(path)

        model = read_pptx_model(path)
        group_block = next(
            p
            for p in _paragraphs(model.sections[0].blocks)
            if any(run.text == "in group" for run in p.content if hasattr(run, "text"))
        )
        assert group_block.box.x == pytest.approx(36.0)
        assert group_block.box.y == pytest.approx(36.0)
        assert group_block.box.width == pytest.approx(72.0)

    def test_extracts_table(self, tmp_path):
        path = tmp_path / "rich.pptx"
        _build_rich_pptx(path)

        model = read_pptx_model(path)
        tables = [block for block in model.sections[0].blocks if isinstance(block, Table)]
        assert len(tables) == 1
        assert [cell_plain(c) for c in tables[0].rows[0].cells] == ["A1", "B1"]
        assert tables[0].box.x == pytest.approx(72.0)

    def test_extracts_chart_data(self, tmp_path):
        path = tmp_path / "rich.pptx"
        _build_rich_pptx(path)

        model = read_pptx_model(path)
        chart_block = next(p for p in _paragraphs(model.sections[0].blocks) if p.properties["pptx"]["shape"]["kind"] == "chart")
        chart = chart_block.properties["pptx"]["chart"]
        assert chart["categories"] == ["Alpha", "Beta"]
        assert chart["series"][0]["name"] == "Score"
        assert chart["series"][0]["values"] == ["10", "20"]

    def test_extracts_image_resource(self, tmp_path):
        path = tmp_path / "rich.pptx"
        image_bytes = _png_bytes(tmp_path)
        _build_rich_pptx(path, image_bytes=image_bytes)

        model = read_pptx_model(path)
        images = [block for block in model.sections[0].blocks if isinstance(block, Image)]
        assert len(images) == 1
        resource = model.resources[images[0].resource_id]
        assert resource.kind == ResourceKind.RASTER_IMAGE
        assert resource.data == image_bytes
        assert model.validate() == []

    def test_extracts_omml_formula(self, tmp_path):
        path = tmp_path / "rich.pptx"
        _build_rich_pptx(path)

        model = read_pptx_model(path)
        paragraphs = _paragraphs(model.sections[0].blocks)
        formulas = [item for p in paragraphs for item in p.content if isinstance(item, Formula)]
        assert len(formulas) == 1
        assert formulas[0].format == "omml"
        assert "oMath" in formulas[0].value
        assert "x" in formulas[0].fallback_text or "y" in formulas[0].fallback_text

    def test_background_fill_and_notes(self, tmp_path):
        path = tmp_path / "rich.pptx"
        _build_rich_pptx(path)

        model = read_pptx_model(path)
        section = model.sections[0]
        assert section.properties["background_fill"] == "#F2F2F2"
        assert section.properties["notes"] == "Speaker notes for test."

    def test_reads_plain_text(self, tmp_path):
        path = tmp_path / "rich.pptx"
        _build_rich_pptx(path)

        text = read_pptx(path)

        assert text.pages == 1
        assert text.source_format.value == "pptx"
        assert "Mixed formatting" in text.plain
        cells = [cell for table in text.tables for row in table.rows for cell in row]
        assert "A1" in cells and "B2" in cells

    def test_imports_corpus_presentation(self):
        model = read_pptx_model(CORPUS_PPTX)

        assert len(model.sections) == 2
        assert model.validate() == []
        tables = [block for block in model.sections[0].blocks if isinstance(block, Table)]
        assert len(tables) == 1
        chart_blocks = [p for p in _paragraphs(model.sections[0].blocks) if p.properties["pptx"]["shape"]["kind"] == "chart"]
        assert len(chart_blocks) == 1
        assert chart_blocks[0].properties["pptx"]["chart"]["chart_type"] == "barChart"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_pptx_model(tmp_path / "missing.pptx")


def cell_plain(cell) -> str:
    return "".join(run.text for block in cell.blocks for run in block.content if hasattr(run, "text"))
