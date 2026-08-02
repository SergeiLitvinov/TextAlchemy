"""Тесты pipeline операций extract.pdf_model и render.docx_model."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import fitz
import pytest

from textalchemy.core.document_model import (
    Box,
    DocumentModel,
    Image,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
)
from textalchemy.core.exceptions import ConvertError
from textalchemy.core.types import DocFormat, Document
from textalchemy.formats.pdf_ocr_types import OcrBlockGeometry, OcrPageResult
from textalchemy.pipeline.extract import extract_pdf_model  # noqa: F401
from textalchemy.pipeline.ingest import ingest_file  # noqa: F401
from textalchemy.pipeline.render import render_docx_model  # noqa: F401


def _make_pdf(path: Path, text: str = "Hello PDF world") -> Path:
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((36, 48), text, fontname="helv", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def _png_bytes(tmp_path: Path) -> bytes:
    from PIL import Image as PillowImage

    path = tmp_path / "_tmp.png"
    PillowImage.new("RGB", (12, 8), "blue").save(path)
    return path.read_bytes()


class TestExtractPdfModelRegistry:
    def test_registered(self):
        from textalchemy.core.registry import all_operations

        ids = {s.id for s in all_operations()}
        assert "extract.pdf_model" in ids


class TestExtractPdfModel:
    def test_not_pdf_returns_empty_model(self):
        doc = Document(path=Path("/fake.txt"), format=DocFormat.TXT, size=0, sha256="")
        model = extract_pdf_model(doc=doc)
        assert isinstance(model, DocumentModel)
        assert model.sections == []
        assert "not a PDF" in model.metadata.get("warnings", [""])[0]

    def test_extracts_text_blocks(self, tmp_path):
        pdf = _make_pdf(tmp_path / "simple.pdf")
        doc = ingest_file(path=pdf)
        model = extract_pdf_model(doc=doc)

        assert isinstance(model, DocumentModel)
        assert len(model.sections) == 1
        blocks = model.sections[0].blocks
        assert len(blocks) >= 1
        plain = "".join(
            run.text for block in blocks if isinstance(block, Paragraph) for run in block.content if isinstance(run, TextRun)
        )
        assert "Hello PDF world" in plain

    def test_sets_metadata(self, tmp_path):
        pdf = _make_pdf(tmp_path / "meta.pdf")
        doc = ingest_file(path=pdf)
        model = extract_pdf_model(doc=doc)

        assert model.source_format == "pdf"
        assert model.metadata.get("engine") == "pymupdf+document-model"
        assert model.metadata.get("pages") == 1

    def test_extracts_table_blocks(self, tmp_path):
        path = tmp_path / "table.pdf"
        doc = fitz.open()
        page = doc.new_page(width=480, height=640)
        page.insert_text((36, 48), "Table test", fontname="helv", fontsize=12)
        rect = fitz.Rect(36, 80, 300, 150)
        page.draw_rect(rect, color=(0, 0, 0), width=1)
        page.draw_line((rect.x0, 110), (rect.x1, 110), color=(0, 0, 0), width=0.5)
        page.draw_line((rect.x0, 140), (rect.x1, 140), color=(0, 0, 0), width=0.5)
        page.draw_line((168, rect.y0), (168, rect.y1), color=(0, 0, 0), width=0.5)
        for xy, value in (((43, 98), "A1"), ((175, 98), "B1"), ((43, 128), "A2"), ((175, 128), "B2")):
            page.insert_text(xy, value, fontname="helv", fontsize=9)
        doc.save(str(path))
        doc.close()

        doc_obj = ingest_file(path=path)
        model = extract_pdf_model(doc=doc_obj)

        assert len(model.sections) == 1
        blocks = model.sections[0].blocks
        tables = [b for b in blocks if isinstance(b, Table)]
        paragraphs = [b for b in blocks if isinstance(b, Paragraph) and any(isinstance(r, TextRun) for r in b.content)]
        assert len(tables) == 1
        assert len(paragraphs) >= 1
        paragraph_text = " ".join(run.text for block in paragraphs for run in block.content if isinstance(run, TextRun))
        assert "A1" not in paragraph_text
        assert isinstance(blocks[0], Paragraph)
        assert isinstance(blocks[1], Table)

    def test_maps_pymupdf_font_flags_correctly(self, tmp_path):
        path = tmp_path / "font-flags.pdf"
        pdf = fitz.open()
        page = pdf.new_page(width=300, height=400)
        page.insert_text((36, 48), "Bold", fontname="Helvetica-Bold", fontsize=12)
        page.insert_text((36, 72), "Italic", fontname="Helvetica-Oblique", fontsize=12)
        pdf.save(path)
        pdf.close()

        model = extract_pdf_model(doc=ingest_file(path=path))
        runs = [
            run
            for block in model.sections[0].blocks
            if isinstance(block, Paragraph)
            for run in block.content
            if isinstance(run, TextRun)
        ]
        bold = next(run for run in runs if run.text == "Bold")
        italic = next(run for run in runs if run.text == "Italic")
        assert bold.style.bold is True
        assert bold.style.italic is False
        assert italic.style.bold is False
        assert italic.style.italic is True

    def test_no_document_raises_type_error(self):
        with pytest.raises(TypeError):
            extract_pdf_model()  # type: ignore[call-arg]


class TestRenderDocxModelRegistry:
    def test_registered(self):
        from textalchemy.core.registry import all_operations

        ids = {s.id for s in all_operations()}
        assert "render.docx_model" in ids


class TestRenderDocxModel:
    def test_creates_docx(self, tmp_path):
        out = tmp_path / "out.docx"
        document = DocumentModel(
            metadata={"title": "Test Doc"},
            sections=[
                Section(
                    blocks=[
                        Paragraph(content=[TextRun("Hello from DocumentModel")]),
                    ]
                )
            ],
        )
        path = render_docx_model(document=document, output_path=out)

        assert path == out
        assert out.is_file()
        from docx import Document

        d = Document(str(out))
        text = "\n".join(p.text for p in d.paragraphs)
        assert "Hello from DocumentModel" in text

    def test_writes_image_resource(self, tmp_path):
        out = tmp_path / "img.docx"
        data = _png_bytes(tmp_path)
        document = DocumentModel(
            resources={
                "img1": Resource("img1", ResourceKind.RASTER_IMAGE, "image/png", data=data),
            },
            sections=[
                Section(
                    blocks=[
                        Paragraph(content=[Image("img1", alt_text="blue square", box=Box(0, 0, 48, 48))]),
                    ]
                )
            ],
        )
        path = render_docx_model(document=document, output_path=out)

        assert path == out
        assert out.is_file()
        assert out.stat().st_size > 200

    def test_writes_table(self, tmp_path):
        out = tmp_path / "table.docx"
        document = DocumentModel(
            sections=[
                Section(
                    blocks=[
                        Table(
                            rows=[
                                TableRow(cells=[TableCell(blocks=[Paragraph(content=[TextRun("A1")])])]),
                                TableRow(cells=[TableCell(blocks=[Paragraph(content=[TextRun("A2")])])]),
                            ]
                        )
                    ]
                )
            ],
        )
        path = render_docx_model(document=document, output_path=out)

        assert path == out
        from docx import Document

        d = Document(str(out))
        assert len(d.tables) == 1
        assert d.tables[0].cell(0, 0).text == "A1"
        assert d.tables[0].cell(1, 0).text == "A2"

    def test_raises_on_empty_document(self, tmp_path):
        out = tmp_path / "empty.docx"
        document = DocumentModel(sections=[])
        path = render_docx_model(document=document, output_path=out)
        assert path == out
        assert out.is_file()

    def test_invalid_path_raises_error(self, tmp_path):
        document = DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun("x")])])])
        with pytest.raises((ValueError, ConvertError, OSError)):
            render_docx_model(document=document, output_path=tmp_path / "\0" / "out.docx")


class TestExtractAndRenderPipeline:
    def test_extract_then_render_pipeline(self, tmp_path):
        pdf = _make_pdf(tmp_path / "pipeline.pdf", "Pipeline test content")
        doc = ingest_file(path=pdf)
        model = extract_pdf_model(doc=doc)

        out = tmp_path / "result.docx"
        result = render_docx_model(document=model, output_path=out)

        assert result == out
        assert out.is_file()
        from docx import Document

        d = Document(str(out))
        text = "\n".join(p.text for p in d.paragraphs)
        assert "Pipeline test content" in text


class TestExtractPdfModelWithOcr:
    def test_use_ocr_merges_ocr_blocks(self, tmp_path):
        pdf = _make_pdf(tmp_path / "ocr_test.pdf", "Existing text layer")
        doc = ingest_file(path=pdf)

        ocr_block = OcrBlockGeometry(text="OCR discovered text", bbox=(10, 10, 200, 30), confidence=0.85, page=1)
        ocr_result = OcrPageResult(blocks=[ocr_block])

        mock_engine = mock.MagicMock()
        mock_engine.is_available = True
        mock_engine.recognize_pdf_geometry.return_value = [ocr_result]

        with mock.patch("textalchemy.recognize.ocr.OcrEngine", return_value=mock_engine):
            model = extract_pdf_model(doc=doc, use_ocr=True)

        assert isinstance(model, DocumentModel)
        assert len(model.sections) >= 1
        blocks = model.sections[0].blocks
        text = " ".join(
            run.text for block in blocks if isinstance(block, Paragraph) for run in block.content if isinstance(run, TextRun)
        )
        assert "OCR discovered text" in text
        assert "Existing text layer" in text
        ocr_paragraph = next(
            block
            for block in blocks
            if isinstance(block, Paragraph) and "OCR discovered text" in block.plain_text
        )
        assert ocr_paragraph.properties["source"] == "ocr"
        assert ocr_paragraph.properties["confidence"] == 0.85

    def test_use_ocr_no_engine_falls_back_gracefully(self, tmp_path):
        pdf = _make_pdf(tmp_path / "ocr_fallback.pdf", "Fallback text")
        doc = ingest_file(path=pdf)

        mock_engine = mock.MagicMock()
        mock_engine.is_available = False

        with mock.patch("textalchemy.recognize.ocr.OcrEngine", return_value=mock_engine):
            model = extract_pdf_model(doc=doc, use_ocr=True)

        assert isinstance(model, DocumentModel)
        assert len(model.sections) >= 1
        assert "OCR engine requested but none available" in model.metadata.get("warnings", [])

    def test_use_ocr_engine_failure_logs_warning(self, tmp_path):
        pdf = _make_pdf(tmp_path / "ocr_fail.pdf", "Text")
        doc = ingest_file(path=pdf)

        mock_engine = mock.MagicMock()
        mock_engine.is_available = True
        mock_engine.recognize_pdf_geometry.side_effect = RuntimeError("OCR crashed")

        with mock.patch("textalchemy.recognize.ocr.OcrEngine", return_value=mock_engine):
            model = extract_pdf_model(doc=doc, use_ocr=True)

        assert isinstance(model, DocumentModel)
        assert any("OCR failed" in w for w in model.metadata.get("warnings", []))
