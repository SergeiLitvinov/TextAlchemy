"""Extract raster images and vector drawings from PDF pages.

Provides:
- ``ExtractedPdfImage`` — actual pixel data from PDF page resources.
- ``PdfVectorDrawing`` — vector path commands (fills, strokes, clipping).
- ``extract_pdf_images()`` — per-page list of extracted images.
- ``extract_pdf_vector_drawings()`` — per-page list of vector drawings.
- ``enrich_geometry_with_images()`` — merge extracted data into a
  ``PdfGeometryDocument`` for downstream consumers (OCR merge, PDF→DOCX).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textalchemy.formats.pdf_geometry import (
    PdfBox,
    PdfGeometryDocument,
    PdfPageGeometry,
)


@dataclass(frozen=True)
class ExtractedPdfImage:
    """Raster image with actual pixel data extracted from PDF."""

    bbox: PdfBox
    number: int
    width: int
    height: int
    extension: str
    colorspace: str
    data: bytes
    xref: int
    page: int
    smask_xref: int = 0

    @property
    def media_type(self) -> str:
        ext = self.extension.lower()
        if ext in ("jpg", "jpeg"):
            return "image/jpeg"
        if ext == "png":
            return "image/png"
        if ext in ("tif", "tiff"):
            return "image/tiff"
        if ext == "gif":
            return "image/gif"
        if ext == "bmp":
            return "image/bmp"
        if ext == "jp2":
            return "image/jp2"
        return f"image/{ext}"


@dataclass(frozen=True)
class PdfVectorDrawing:
    """One vector drawing element from a PDF page.

    Each drawing corresponds to a group in PyMuPDF's ``page.get_drawings()``.
    The ``items`` list stores path commands as raw dict values.
    """

    bbox: PdfBox
    number: int
    page: int
    items: tuple[dict[str, Any], ...] = ()
    fill: str | None = None
    stroke: str | None = None
    color: tuple[float, float, float] | None = None
    width: float = 0.0
    fill_opacity: float = 1.0
    stroke_opacity: float = 1.0
    even_odd: bool = False
    close_path: bool = True
    dashes: str = ""
    line_join: int = 0
    line_cap: int = 0

    @property
    def is_path(self) -> bool:
        return bool(self.items)


def _to_int(value: object) -> int:
    """Convert value to int, handling PyMuPDF tuples like (0, 0, 0)."""
    if value is None:
        return 0
    if isinstance(value, (list, tuple)):
        return int(value[0]) if value else 0
    return int(value)  # type: ignore[arg-type]


def extract_pdf_images(path: str | Path) -> tuple[list[ExtractedPdfImage], list[str]]:
    """Extract all raster image pixel data from a PDF.

    Uses PyMuPDF's ``page.get_images()`` + ``document.extract_image()`` to
    retrieve the actual bytes of every image embedded in the PDF.  Returns
    a flat list of ``ExtractedPdfImage`` sorted by (page, number).

    Images are deduplicated by xref — if the same image is referenced
    multiple times on a page (or across pages), only the first occurrence
    holds the pixel data; subsequent occurrences reference the same ``xref``.
    """
    import fitz

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)

    images: list[ExtractedPdfImage] = []
    warnings: list[str] = []
    seen_xrefs: set[int] = set()

    with fitz.open(str(source)) as document:
        for page_number, page in enumerate(document, start=1):
            page_dict = page.get_text("dict", sort=False) or {}
            image_blocks = [block for block in page_dict.get("blocks", []) if block.get("type") == 1]

            for block_index, block in enumerate(image_blocks):
                block_number = int(block.get("number", block_index))
                image_info_list = page.get_images(full=True)

                for item in image_info_list:
                    xref = int(item[0])
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    try:
                        extracted = document.extract_image(xref)
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(f"page {page_number} image xref {xref}: {type(exc).__name__}: {exc}")
                        continue

                    data = extracted.get("image", b"")
                    if not data:
                        continue

                    images.append(
                        ExtractedPdfImage(
                            bbox=block.get("bbox", (0.0, 0.0, 0.0, 0.0)),
                            number=block_number,
                            width=int(extracted.get("width", 0)),
                            height=int(extracted.get("height", 0)),
                            extension=str(extracted.get("ext", "")),
                            colorspace=str(extracted.get("colorspace", "")),
                            data=data,
                            xref=xref,
                            page=page_number,
                            smask_xref=int(item[1]) if item[1] > 0 else 0,
                        )
                    )

    images.sort(key=lambda img: (img.page, img.number))
    return images, warnings


def extract_pdf_vector_drawings(path: str | Path) -> tuple[list[PdfVectorDrawing], list[str]]:
    """Extract vector drawing commands from a PDF.

    Uses PyMuPDF's ``page.get_drawings()`` to retrieve vector paths,
    fills, strokes, and clipping regions.  Returns a flat list of
    ``PdfVectorDrawing`` sorted by (page, number).
    """
    import fitz

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)

    drawings: list[PdfVectorDrawing] = []
    warnings: list[str] = []

    with fitz.open(str(source)) as document:
        for page_number, page in enumerate(document, start=1):
            try:
                raw = page.get_drawings()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"page {page_number} get_drawings: {type(exc).__name__}: {exc}")
                continue

            for draw_index, draw in enumerate(raw):
                rect = draw.get("rect")
                bbox = (
                    (
                        float(rect.x0),
                        float(rect.y0),
                        float(rect.x1),
                        float(rect.y1),
                    )
                    if rect
                    else (0.0, 0.0, 0.0, 0.0)
                )

                items = tuple(draw.get("items", []))
                fill_color = draw.get("fill")
                stroke_color = draw.get("stroke")
                color_val = draw.get("color")

                drawings.append(
                    PdfVectorDrawing(
                        bbox=bbox,
                        number=draw_index + 1,
                        page=page_number,
                        items=items,
                        fill=str(fill_color) if fill_color is not None else None,
                        stroke=str(stroke_color) if stroke_color is not None else None,
                        color=(
                            tuple(float(c) for c in color_val) if color_val and isinstance(color_val, (list, tuple)) else None
                        ),
                        width=float(draw.get("width", 0.0) or 0.0),
                        fill_opacity=float(draw.get("fill_opacity", 1.0) or 1.0),
                        stroke_opacity=float(draw.get("stroke_opacity", 1.0) or 1.0),
                        even_odd=bool(draw.get("even_odd", False)),
                        close_path=bool(draw.get("closePath", True)),
                        dashes=str(draw.get("dashes", "")),
                        line_join=_to_int(draw.get("lineJoin", 0)),
                        line_cap=_to_int(draw.get("lineCap", 0)),
                    )
                )

    return drawings, warnings


def enrich_geometry_with_images(
    geometry: PdfGeometryDocument,
    images: list[ExtractedPdfImage] | None = None,
    vector_drawings: list[PdfVectorDrawing] | None = None,
) -> PdfGeometryDocument:
    """Merge extracted images and vector drawings into a geometry document.

    This is a convenience function that enriches each ``PdfPageGeometry``
    in the document with the supplied extracted images and vector drawings,
    grouped by page number.
    """
    if not images and not vector_drawings:
        return geometry

    images_by_page: dict[int, list[ExtractedPdfImage]] = {}
    if images:
        for img in images:
            images_by_page.setdefault(img.page, []).append(img)

    vectors_by_page: dict[int, list[PdfVectorDrawing]] = {}
    if vector_drawings:
        for v in vector_drawings:
            vectors_by_page.setdefault(v.page, []).append(v)

    enriched_pages: list[PdfPageGeometry] = []
    for page in geometry.pages:
        pn = page.number
        page_images = tuple(images_by_page.get(pn, []))
        page_vectors = tuple(vectors_by_page.get(pn, []))
        enriched_pages.append(
            PdfPageGeometry(
                number=page.number,
                width=page.width,
                height=page.height,
                rotation=page.rotation,
                text_blocks=page.text_blocks,
                image_blocks=page.image_blocks,
                tables=page.tables,
                extracted_images=page_images,
                vector_drawings=page_vectors,
            )
        )

    return PdfGeometryDocument(
        pages=enriched_pages,
        metadata=geometry.metadata,
        engine=geometry.engine,
        warnings=geometry.warnings,
    )


__all__ = [
    "ExtractedPdfImage",
    "PdfVectorDrawing",
    "enrich_geometry_with_images",
    "extract_pdf_images",
    "extract_pdf_vector_drawings",
]
