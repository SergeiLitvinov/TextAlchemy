"""Тесты разделённых геометрического и семантического слоёв PDF."""

import io

import fitz
from PIL import Image

from tests.corpus.multiformat import build_multiformat_corpus
from textalchemy.core.types import BlockType
from textalchemy.formats.pdf import read_pdf_geometry
from textalchemy.formats.pdf_geometry import (
    PdfGeometryDocument,
    PdfLineGeometry,
    PdfPageGeometry,
    PdfSpanGeometry,
    PdfTextBlockGeometry,
)
from textalchemy.formats.pdf_semantic import analyze_pdf_geometry


def _build_positioned_pdf(path):
    document = fitz.open()
    page = document.new_page(width=300, height=400)
    page.insert_text((40, 60), "Geometry heading", fontname="helv", fontsize=14)
    page.insert_text((40, 95), "Semantic paragraph", fontname="Times-Roman", fontsize=11)
    document.set_metadata({"title": "Layered PDF", "author": "TextAlchemy"})
    document.save(path)
    document.close()


def test_read_pdf_geometry_preserves_pages_coordinates_and_spans(tmp_path):
    path = tmp_path / "positioned.pdf"
    _build_positioned_pdf(path)

    geometry = read_pdf_geometry(str(path))

    assert geometry.engine == "pymupdf"
    assert geometry.metadata["title"] == "Layered PDF"
    assert len(geometry.pages) == 1
    page = geometry.pages[0]
    assert page.number == 1
    assert page.width == 300
    assert page.height == 400
    assert len(page.text_blocks) == 2
    heading = page.text_blocks[0]
    assert heading.text == "Geometry heading"
    assert heading.bbox[0] == 40
    assert heading.bbox[1] < 60 < heading.bbox[3]
    assert heading.lines[0].spans[0].font == "Helvetica"
    assert heading.lines[0].spans[0].size == 14


def test_analyze_pdf_geometry_builds_semantic_text_without_reopening_pdf(tmp_path):
    path = tmp_path / "semantic.pdf"
    _build_positioned_pdf(path)
    geometry = read_pdf_geometry(str(path))

    text = analyze_pdf_geometry(geometry)

    assert text.engine == "pymupdf"
    assert text.pages == 1
    assert text.plain == "Geometry heading\nSemantic paragraph"
    assert [block.page for block in text.blocks] == [1, 1]
    assert text.blocks[0].meta["bbox"] == list(geometry.pages[0].text_blocks[0].bbox)
    assert text.blocks[0].meta["page_width"] == 300
    assert text.blocks[0].meta["page_height"] == 400


def _geometry_block(number, text, bbox):
    span = PdfSpanGeometry(text=text, bbox=bbox, origin=(bbox[0], bbox[3]))
    line = PdfLineGeometry(spans=(span,), bbox=bbox)
    return PdfTextBlockGeometry(lines=(line,), bbox=bbox, number=number)


def test_analyze_pdf_geometry_orders_spanning_blocks_and_two_columns():
    page = PdfPageGeometry(
        number=1,
        width=300,
        height=400,
        text_blocks=(
            _geometry_block(0, "Document title", (20, 20, 280, 45)),
            _geometry_block(1, "Right first", (170, 70, 280, 90)),
            _geometry_block(2, "Left first", (20, 65, 130, 85)),
            _geometry_block(3, "Page footer", (20, 350, 280, 370)),
            _geometry_block(4, "Right second", (170, 110, 280, 130)),
            _geometry_block(5, "Left second", (20, 105, 130, 125)),
        ),
    )

    text = analyze_pdf_geometry(PdfGeometryDocument(pages=[page]))

    assert [block.text for block in text.blocks] == [
        "Document title",
        "Left first",
        "Left second",
        "Right first",
        "Right second",
        "Page footer",
    ]
    assert [block.meta["reading_order"] for block in text.blocks] == list(range(6))
    assert [block.meta["column"] for block in text.blocks] == [None, 0, 0, 1, 1, None]
    assert all(block.meta["column_count"] == 2 for block in text.blocks)
    assert text.blocks[0].meta["spanning"] is True
    assert text.blocks[-1].meta["spanning"] is True
    assert text.blocks[1].meta["gutter"] == [130, 170]


def test_pdf_geometry_and_semantics_restore_ruled_table(tmp_path):
    pdf = build_multiformat_corpus(tmp_path)["pdf"]

    geometry = read_pdf_geometry(pdf)
    table = geometry.pages[0].tables[0]
    text = analyze_pdf_geometry(geometry)
    table_blocks = [block for block in text.blocks if block.type is BlockType.TABLE]

    assert table.strategy == "lines_strict"
    assert table.row_count == 3
    assert table.column_count == 3
    assert table.rows == (
        ("Feature", "Expected", "Observed"),
        ("Text", "Editable", "Exact"),
        ("Vector", "Native", "Preserved"),
    )
    assert len(table.cells) == 9
    assert all(cell.bbox is not None for cell in table.cells)
    assert len(text.tables) == 1
    assert text.tables[0].rows == [list(row) for row in table.rows]
    assert len(table_blocks) == 1
    assert table_blocks[0].meta["table_strategy"] == "lines_strict"
    assert table_blocks[0].meta["row_count"] == 3
    assert text.plain.count("Feature") == 1


def test_pdf_geometry_restores_borderless_table_by_text_alignment(tmp_path):
    path = tmp_path / "borderless-table.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=240)
    for y, values in ((60, ("Name", "Value")), (90, ("Alpha", "10")), (120, ("Beta", "20"))):
        page.insert_text((40, y), values[0], fontname="helv", fontsize=10)
        page.insert_text((180, y), values[1], fontname="helv", fontsize=10)
    document.save(path, no_new_id=True)
    document.close()

    geometry = read_pdf_geometry(path)

    assert len(geometry.pages[0].tables) == 1
    table = geometry.pages[0].tables[0]
    assert table.strategy == "text"
    assert table.rows == (("Name", "Value"), ("Alpha", "10"), ("Beta", "20"))


def test_pdf_semantics_classifies_captions_formulas_and_repeated_running_content(tmp_path):
    path = tmp_path / "classified.pdf"
    image_buffer = io.BytesIO()
    Image.new("RGB", (40, 24), "#2E74B5").save(image_buffer, format="PNG")
    document = fitz.open()
    for page_number in range(1, 4):
        page = document.new_page(width=300, height=400)
        page.insert_text((35, 20), "Journal of Conversion", fontname="helv", fontsize=8)
        page.insert_text((35, 90), f"Body paragraph on sheet {page_number}.", fontname="Times-Roman", fontsize=11)
        if page_number == 1:
            page.insert_text((75, 165), "E = mc^2 + integral_0^1 x^2", fontname="cour", fontsize=13)
            page.insert_image(fitz.Rect(80, 210, 220, 250), stream=image_buffer.getvalue())
            page.insert_text((75, 270), "Figure 1. Control curve", fontname="helv", fontsize=9)
        page.insert_text((125, 385), f"Page {page_number}", fontname="helv", fontsize=8)
    document.save(path, no_new_id=True)
    document.close()

    geometry = read_pdf_geometry(path)
    assert [page.tables for page in geometry.pages] == [(), (), ()]
    text = analyze_pdf_geometry(geometry)
    headers = [block for block in text.blocks if block.meta.get("semantic_role") == "header"]
    footers = [block for block in text.blocks if block.meta.get("semantic_role") == "footer"]
    equations = [block for block in text.blocks if block.type is BlockType.EQUATION]
    captions = [block for block in text.blocks if block.type is BlockType.CAPTION]

    assert len(headers) == 3
    assert len(footers) == 3
    assert all(block.meta["excluded_from_plain"] is True for block in [*headers, *footers])
    assert all(block.meta["semantic_confidence"] == 0.98 for block in [*headers, *footers])
    assert "Journal of Conversion" not in text.plain
    assert "Page 1" not in text.plain
    assert len(equations) == 1
    assert equations[0].meta["semantic_role"] == "formula"
    assert "equality" in equations[0].meta["semantic_evidence"]
    assert equations[0].meta["semantic_confidence"] >= 0.65
    assert len(captions) == 1
    assert captions[0].text == "Figure 1. Control curve"
    assert captions[0].meta["semantic_evidence"] == ["caption-prefix", "near-image-0"]
