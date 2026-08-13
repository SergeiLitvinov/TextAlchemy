"""Tests for PDF image/vector extraction (pdf_images)."""

from __future__ import annotations

import io

import fitz
import pytest
from PIL import Image

from textalchemy.core.color import ColorValue
from textalchemy.formats.pdf_images import (
    ExtractedPdfImage,
    enrich_geometry_with_images,
    extract_pdf_images,
    extract_pdf_vector_drawings,
)


def _make_pdf_with_images(path: str, image_count: int = 1) -> None:
    """Create a PDF with raster images embedded."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    for i in range(image_count):
        img_data = io.BytesIO()
        img = Image.new("RGB", (50, 50), (255, 0, 0))
        img.save(img_data, format="PNG")
        img_data.seek(0)
        page.insert_image(
            fitz.Rect(10 + i * 60, 30, 60 + i * 60, 80),
            stream=img_data.read(),
        )
    doc.save(path)
    doc.close()


def _make_pdf_with_vector(path: str) -> None:
    """Create a PDF with vector drawings (a rectangle)."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(50, 50, 200, 150))
    shape.finish(fill=(0.0, 0.0, 1.0), color=(0.0, 0.0, 0.0), width=2)
    shape.commit()
    doc.save(path)
    doc.close()


def _make_empty_pdf(path: str) -> None:
    doc = fitz.open()
    doc.new_page(width=300, height=400)
    doc.save(path)
    doc.close()


class TestExtractPdfImages:
    def test_extract_single_image(self, tmp_path):
        path = tmp_path / "single_img.pdf"
        _make_pdf_with_images(str(path), image_count=1)

        images, warnings = extract_pdf_images(str(path))

        assert len(images) == 1
        img = images[0]
        assert img.width == 50
        assert img.height == 50
        assert img.extension == "png"
        assert img.page == 1
        assert len(img.data) > 0
        assert warnings == []

    def test_extract_multiple_images(self, tmp_path):
        path = tmp_path / "multi_img.pdf"
        _make_pdf_with_images(str(path), image_count=3)

        images, warnings = extract_pdf_images(str(path))

        assert len(images) >= 1
        assert all(img.page == 1 for img in images)
        assert all(len(img.data) > 0 for img in images)

    def test_extract_no_images(self, tmp_path):
        path = tmp_path / "no_img.pdf"
        _make_empty_pdf(str(path))

        images, warnings = extract_pdf_images(str(path))

        assert images == []
        assert warnings == []

    def test_extract_from_nonexistent_file(self, tmp_path):
        path = tmp_path / "does_not_exist.pdf"
        with pytest.raises(FileNotFoundError):
            extract_pdf_images(str(path))

    def test_media_type_property(self):
        img = ExtractedPdfImage(
            bbox=(0, 0, 50, 50),
            number=1,
            width=50,
            height=50,
            extension="png",
            colorspace="RGB",
            data=b"fake",
            xref=1,
            page=1,
        )
        assert img.media_type == "image/png"

        img_jpeg = ExtractedPdfImage(
            bbox=(0, 0, 100, 100),
            number=2,
            width=100,
            height=100,
            extension="jpg",
            colorspace="RGB",
            data=b"fake",
            xref=2,
            page=1,
        )
        assert img_jpeg.media_type == "image/jpeg"


class TestExtractVectorDrawings:
    def test_extract_vector_rectangle(self, tmp_path):
        path = tmp_path / "vector.pdf"
        _make_pdf_with_vector(str(path))

        drawings, warnings = extract_pdf_vector_drawings(str(path))

        assert len(drawings) >= 1
        d = drawings[0]
        assert d.page == 1
        assert d.items is not None
        assert isinstance(d.fill, ColorValue)
        assert d.fill.to_hex() == "#0000FF"
        assert isinstance(d.stroke, ColorValue)
        assert d.stroke.to_hex() == "#000000"
        assert d.width > 0

    def test_extract_no_vector(self, tmp_path):
        path = tmp_path / "no_vector.pdf"
        _make_empty_pdf(str(path))

        drawings, warnings = extract_pdf_vector_drawings(str(path))

        assert drawings == []


class TestEnrichGeometry:
    def test_enrich_with_images(self, tmp_path):
        from textalchemy.formats.pdf_geometry import extract_pdf_geometry

        path = tmp_path / "enrich.pdf"
        _make_pdf_with_images(str(path))

        geometry = extract_pdf_geometry(str(path))
        images, _ = extract_pdf_images(str(path))

        enriched = enrich_geometry_with_images(geometry, images=images)

        assert len(enriched.pages) == 1
        page = enriched.pages[0]
        assert len(page.extracted_images) == 1
        assert page.extracted_images[0].width == 50

    def test_enrich_with_vectors(self, tmp_path):
        from textalchemy.formats.pdf_geometry import extract_pdf_geometry

        path = tmp_path / "enrich_vec.pdf"
        _make_pdf_with_vector(str(path))

        geometry = extract_pdf_geometry(str(path))
        vectors, _ = extract_pdf_vector_drawings(str(path))

        enriched = enrich_geometry_with_images(geometry, vector_drawings=vectors)

        assert len(enriched.pages) == 1
        page = enriched.pages[0]
        assert len(page.vector_drawings) >= 1

    def test_enrich_no_data_returns_original(self, tmp_path):
        from textalchemy.formats.pdf_geometry import extract_pdf_geometry

        path = tmp_path / "no_enrich.pdf"
        _make_empty_pdf(str(path))

        geometry = extract_pdf_geometry(str(path))
        enriched = enrich_geometry_with_images(geometry)

        assert enriched is geometry

    def test_enrich_preserves_text_and_tables(self, tmp_path):
        from textalchemy.formats.pdf_geometry import extract_pdf_geometry

        path = tmp_path / "preserve.pdf"
        doc = fitz.open()
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), "Hello world", fontname="helv", fontsize=11)
        img_data = io.BytesIO()
        img = Image.new("RGB", (30, 30), (0, 255, 0))
        img.save(img_data, format="PNG")
        img_data.seek(0)
        page.insert_image(fitz.Rect(200, 200, 230, 230), stream=img_data.read())
        doc.save(path)
        doc.close()

        geometry = extract_pdf_geometry(str(path))
        images, _ = extract_pdf_images(str(path))

        enriched = enrich_geometry_with_images(geometry, images=images)

        page = enriched.pages[0]
        assert len(page.text_blocks) == 1
        assert "Hello" in page.text_blocks[0].text
        assert len(page.extracted_images) == 1


@pytest.mark.parametrize("method", ["images", "vectors", "both"])
def test_extract_roundtrip(method, tmp_path):
    path = tmp_path / f"roundtrip_{method}.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    # vector
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(10, 10, 100, 100))
    shape.finish(fill=(1, 0, 0))
    shape.commit()
    # raster
    img_data = io.BytesIO()
    img = Image.new("RGB", (20, 20), (0, 0, 255))
    img.save(img_data, format="PNG")
    img_data.seek(0)
    page.insert_image(fitz.Rect(200, 200, 220, 220), stream=img_data.read())
    doc.save(path)
    doc.close()

    if method in ("images", "both"):
        images, _ = extract_pdf_images(str(path))
        assert len(images) >= 1

    if method in ("vectors", "both"):
        vectors, _ = extract_pdf_vector_drawings(str(path))
        assert len(vectors) >= 1
