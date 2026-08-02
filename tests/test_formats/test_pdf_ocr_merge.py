"""Tests for pdf_ocr_merge — text layer + OCR merging."""

from __future__ import annotations

import fitz
import pytest

from textalchemy.core.types import BlockType
from textalchemy.formats.pdf import read_pdf_geometry
from textalchemy.formats.pdf_ocr_merge import (
    _bbox_overlap,
    _merge_text_layer_and_ocr_page,
    _page_text_coverage,
    merge_pdf_with_ocr,
)
from textalchemy.formats.pdf_ocr_types import OcrBlockGeometry, OcrPageResult


def _make_simple_pdf(path, text_blocks: list[tuple[str, float, float]]) -> None:
    """Create a PDF with positioned text blocks at given (x, y)."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    for text, x, y in text_blocks:
        page.insert_text((x, y), text, fontname="helv", fontsize=11)
    doc.set_metadata({"title": "Merge Test"})
    doc.save(path)
    doc.close()


def test_bbox_overlap_full():
    a = (10, 10, 100, 100)
    b = (10, 10, 100, 100)
    assert _bbox_overlap(a, b) == 1.0


def test_bbox_overlap_half():
    a = (10, 10, 100, 100)
    b = (50, 10, 140, 100)
    # IoU: overlap_area=4500, union=11700 → 4500/11700 ≈ 0.3846
    assert _bbox_overlap(a, b) == pytest.approx(0.3846, rel=1e-3)


def test_bbox_overlap_none():
    a = (10, 10, 100, 100)
    b = (200, 200, 300, 300)
    assert _bbox_overlap(a, b) == 0.0


def test_page_text_coverage():
    cov = _page_text_coverage("Hello world", 300, 400)
    assert cov > 0
    cov_empty = _page_text_coverage("", 300, 400)
    assert cov_empty == 0.0


def test_merge_pdf_with_ocr_falls_back_to_text_layer(tmp_path):
    path = tmp_path / "text_only.pdf"
    _make_simple_pdf(path, [("Hello from text layer", 40, 60)])

    geometry = read_pdf_geometry(str(path))
    text = merge_pdf_with_ocr(geometry, ocr_pages=None)

    assert text.engine == "pymupdf"
    assert text.plain == "Hello from text layer"
    assert len(text.blocks) == 1
    assert text.blocks[0].meta["source"] == "text_layer"
    assert text.blocks[0].meta["confidence"] == 1.0


def test_merge_pdf_with_ocr_uses_ocr_when_text_layer_empty(tmp_path):
    path = tmp_path / "no_text.pdf"
    doc = fitz.open()
    doc.new_page(width=300, height=400)
    doc.save(path)
    doc.close()

    geometry = read_pdf_geometry(str(path))
    ocr_blocks = [
        OcrBlockGeometry(text="OCR recognised text", bbox=(30, 50, 270, 70), confidence=0.85, page=1),
        OcrBlockGeometry(text="Second OCR line", bbox=(30, 80, 200, 100), confidence=0.78, page=1),
    ]
    ocr_pages = [OcrPageResult(blocks=ocr_blocks)]

    text = merge_pdf_with_ocr(geometry, ocr_pages=ocr_pages)

    assert text.engine == "pymupdf+ocr"
    assert "OCR recognised text" in text.plain
    assert "Second OCR line" in text.plain
    assert text.blocks[0].meta["source"] == "ocr"
    assert text.blocks[0].meta["confidence"] == 0.85


def test_merge_pdf_with_ocr_prefers_text_layer_when_sufficient(tmp_path):
    path = tmp_path / "rich_text.pdf"
    _make_simple_pdf(
        path,
        [
            ("This is a long enough text layer that should be preferred over OCR", 40, 60),
        ],
    )

    geometry = read_pdf_geometry(str(path))
    ocr_blocks = [
        OcrBlockGeometry(text="OCR hallucination", bbox=(30, 50, 270, 70), confidence=0.95, page=1),
    ]
    ocr_pages = [OcrPageResult(blocks=ocr_blocks)]

    text = merge_pdf_with_ocr(geometry, ocr_pages=ocr_pages)

    assert text.engine == "pymupdf+ocr"
    assert "This is a long enough text layer" in text.plain
    # Text layer block is first
    assert text.blocks[0].meta["source"] == "text_layer"
    # OCR block may not be added if it overlaps with text layer
    assert any(b.meta["source"] == "ocr" for b in text.blocks) is False


def test_merge_text_layer_and_ocr_page_merge(tmp_path):
    """Test low-level page merge with mixed text layer and OCR."""
    text_blocks = _make_text_blocks(
        [
            ("Visible text", (40, 50, 200, 70), 0),
        ]
    )
    ocr_page = OcrPageResult(
        blocks=[
            OcrBlockGeometry(text="OCR extra", bbox=(40, 100, 200, 120), confidence=0.9, page=1),
        ]
    )

    merged = _merge_text_layer_and_ocr_page(
        text_blocks,
        [],
        ocr_page,
        page_number=1,
        page_width=300,
        page_height=400,
    )

    assert len(merged) >= 1
    assert any(b.text == "Visible text" for b in merged)
    assert any(b.text == "OCR extra" for b in merged)


def test_pdf_geometry_still_produces_tables_with_ocr_merge(tmp_path):
    """Table detection should work even with the OCR merge pipeline."""
    from tests.corpus.multiformat import build_multiformat_corpus

    pdf = build_multiformat_corpus(tmp_path)["pdf"]
    geometry = read_pdf_geometry(pdf)

    text = merge_pdf_with_ocr(geometry, ocr_pages=None)
    table_blocks = [b for b in text.blocks if b.type is BlockType.TABLE]

    assert len(table_blocks) >= 1
    assert "Feature" in table_blocks[0].text
    assert text.blocks[0].meta["source"] == "text_layer"


def test_ocr_branch_preserves_tables_and_semantic_classification(tmp_path):
    from tests.corpus.multiformat import build_multiformat_corpus

    pdf = build_multiformat_corpus(tmp_path)["pdf"]
    geometry = read_pdf_geometry(pdf)
    ocr_pages = [
        OcrPageResult(
            blocks=[OcrBlockGeometry(text="OCR margin note", bbox=(36, 610, 150, 625), confidence=0.88, page=1)]
        ),
        OcrPageResult(),
    ]

    text = merge_pdf_with_ocr(geometry, ocr_pages=ocr_pages)

    assert any(block.type is BlockType.TABLE for block in text.blocks)
    assert any(block.type is BlockType.CAPTION and block.text.startswith("Figure 1") for block in text.blocks)
    assert any(block.meta.get("source") == "ocr" and block.meta.get("confidence") == 0.88 for block in text.blocks)


def test_read_pdf_with_ocr_no_engine(tmp_path):
    """read_pdf_with_ocr with ocr_engine=None should work as pure geometry."""
    _make_simple_pdf(tmp_path / "simple.pdf", [("No OCR engine", 40, 60)])

    from textalchemy.formats.pdf_ocr_merge import read_pdf_with_ocr

    text = read_pdf_with_ocr(str(tmp_path / "simple.pdf"), ocr_engine=None)

    assert "No OCR engine" in text.plain
    assert text.engine == "pymupdf"


def _make_text_blocks(blocks_data):
    """Helper: create PdfTextBlockGeometry list from (text, bbox, number)."""
    from textalchemy.formats.pdf_geometry import PdfLineGeometry, PdfSpanGeometry, PdfTextBlockGeometry

    result = []
    for text, bbox, number in blocks_data:
        span = PdfSpanGeometry(text=text, bbox=bbox, origin=(bbox[0], bbox[3]))
        line = PdfLineGeometry(spans=(span,), bbox=bbox)
        result.append(PdfTextBlockGeometry(lines=(line,), bbox=bbox, number=number))
    return result
