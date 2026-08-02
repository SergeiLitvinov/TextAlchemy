"""Универсальный ридер: Document → Text.

Выбирает движок по ``Document.format``. Сейчас PDF идёт по цепочке
``pdfplumber → pypdf → pymupdf geometry → semantics`` (см. formats/pdf.py).
"""

from __future__ import annotations

from typing import Any

from textalchemy.core.document_model import (
    Block as RichBlock,
)
from textalchemy.core.document_model import (
    Box,
    ConversionMode,
    DocumentModel,
    Length,
    PageSettings,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
)
from textalchemy.core.document_model import (
    Image as RichImage,
)
from textalchemy.core.document_model import (
    Table as RichTable,
)
from textalchemy.core.registry import operation
from textalchemy.core.types import DocFormat, Document, Text


@operation(
    "extract.text",
    input_type="Document",
    output_type="Text",
    input_param="doc",
    description="Document → Text (универсальный ридер по формату).",
    tags=["extract"],
)
def extract_text(*, doc: Document) -> Text:
    if doc.format == DocFormat.PDF:
        from textalchemy.formats.pdf import read_pdf

        return read_pdf(str(doc.path))
    if doc.format == DocFormat.DOCX:
        from textalchemy.formats.docx import read_docx

        return read_docx(doc.path)
    if doc.format == DocFormat.TXT:
        from textalchemy.formats.txt import read_txt

        return read_txt(doc.path)
    if doc.format == DocFormat.DJVU:
        from textalchemy.formats.txt import read_djvu

        return read_djvu(doc.path)
    if doc.format == DocFormat.EPUB:
        from textalchemy.formats.epub import read_epub

        return read_epub(doc.path)
    return Text(
        source_format=doc.format,
        engine="none",
        warnings=[f"no reader for format {doc.format.value!r}"],
    )


__all__ = ["extract_text", "extract_pdf_model"]


@operation(
    "extract.pdf_model",
    input_type="Document",
    output_type="DocumentModel",
    input_param="doc",
    description="PDF → DocumentModel (геометрия, таблицы, изображения, векторные рисунки).",
    tags=["extract", "pdf", "document-model"],
)
def extract_pdf_model(
    *,
    doc: Document,
    use_ocr: bool = False,
    ocr_backend: str = "",
    handwriting: bool = False,
    use_gpu: bool = False,
) -> DocumentModel:
    """Извлечь PDF в богатую модель с текстом, таблицами и изображениями.

    Args:
        doc: Документ PDF.
        use_ocr: Включить OCR-слияние с текстовым слоем.
        ocr_backend: Имя OCR-бэкенда (tesseract/easyocr/paddle).
        handwriting: Режим распознавания рукописного текста.
        use_gpu: Использовать GPU для OCR.

    Returns:
        ``DocumentModel`` с текстом, таблицами и изображениями.
    """
    if doc.format != DocFormat.PDF:
        return DocumentModel(
            sections=[],
            source_format=doc.format.value,
            metadata={"engine": "none", "warnings": [f"extract.pdf_model: not a PDF: {doc.format.value!r}"]},
        )

    from textalchemy.formats.pdf import read_pdf_geometry
    from textalchemy.formats.pdf_images import (
        enrich_geometry_with_images,
        extract_pdf_images,
        extract_pdf_vector_drawings,
    )

    path = str(doc.path)
    geometry = read_pdf_geometry(path)
    engine = "pymupdf+document-model"

    # Optionally merge with OCR
    if use_ocr:
        from textalchemy.recognize.ocr import OcrEngine

        ocr_engine = OcrEngine(
            backend=ocr_backend if ocr_backend else "auto",
            use_gpu=use_gpu,
        )
        if ocr_engine.is_available:
            try:
                ocr_pages = ocr_engine.recognize_pdf_geometry(path, handwriting=handwriting)
                geometry = _merge_ocr_into_geometry(geometry, ocr_pages)
                engine = "pymupdf+ocr+document-model"
            except Exception as exc:  # noqa: BLE001
                geometry.warnings.append(f"OCR failed: {exc}")
        else:
            geometry.warnings.append("OCR engine requested but none available")

    images, img_warnings = extract_pdf_images(path)
    vectors, vec_warnings = extract_pdf_vector_drawings(path)
    geometry = enrich_geometry_with_images(geometry, images, vectors)

    all_warnings: list[str] = list(geometry.warnings) + img_warnings + vec_warnings

    sections: list[Section] = []
    resources: dict[str, Resource] = {}

    for page in geometry.pages:
        blocks: list[RichBlock] = []

        for tb in page.text_blocks:
            text = tb.text
            if not text.strip():
                continue
            runs: list[TextRun] = []
            for line in tb.lines:
                for span in line.spans:
                    style = TextStyle(
                        font_family=span.font or None,
                        font_size=Length(span.size) if span.size else None,
                        bold=bool(span.flags & 2),
                        italic=bool(span.flags & 1),
                    )
                    runs.append(TextRun(text=span.text, style=style))
            if not runs:
                runs.append(TextRun(text=text))
            bbox = tb.bbox
            box = Box(x=bbox[0], y=bbox[1], width=bbox[2] - bbox[0], height=bbox[3] - bbox[1]) if len(bbox) == 4 else None
            blocks.append(Paragraph(content=runs, box=box))

        for img in page.extracted_images:
            resource_id = f"p{page.number}_img{img.xref}"
            if resource_id not in resources and img.data:
                resources[resource_id] = Resource(
                    id=resource_id,
                    kind=ResourceKind.RASTER_IMAGE,
                    media_type=img.media_type,
                    data=img.data,
                    filename=img.extension,
                )
            elif resource_id not in resources:
                continue
            bbox = img.bbox
            box = Box(x=bbox[0], y=bbox[1], width=bbox[2] - bbox[0], height=bbox[3] - bbox[1]) if len(bbox) == 4 else None
            blocks.append(Paragraph(content=[RichImage(resource_id=resource_id, box=box)]))

        for vec in page.vector_drawings:
            resource_id = f"p{page.number}_vec{vec.number}"
            if resource_id not in resources:
                resources[resource_id] = Resource(
                    id=resource_id,
                    kind=ResourceKind.VECTOR_IMAGE,
                    media_type="application/pdf+vector",
                    data=b"",
                    properties={"items": list(vec.items), "fill": vec.fill, "stroke": vec.stroke},
                )
            bbox = vec.bbox
            box = Box(x=bbox[0], y=bbox[1], width=bbox[2] - bbox[0], height=bbox[3] - bbox[1]) if len(bbox) == 4 else None
            alt = f"Vector drawing {vec.number} on page {vec.page}"
            blocks.append(Paragraph(content=[RichImage(resource_id=resource_id, box=box, alt_text=alt)]))

        for table in page.tables:
            rich_rows: list[TableRow] = []
            for row_data in table.rows:
                cells = [TableCell(blocks=[Paragraph(content=[TextRun(text=cell_text)])]) for cell_text in row_data]
                rich_rows.append(TableRow(cells=cells))
            bbox = table.bbox
            box = Box(x=bbox[0], y=bbox[1], width=bbox[2] - bbox[0], height=bbox[3] - bbox[1]) if len(bbox) == 4 else None
            blocks.append(RichTable(rows=rich_rows, box=box))

        sections.append(
            Section(
                blocks=blocks,
                page=PageSettings(
                    width=Length(page.width),
                    height=Length(page.height),
                ),
            )
        )

    metadata: dict[str, Any] = {"engine": engine, "pages": len(sections), "warnings": all_warnings}
    metadata.update(geometry.metadata)

    return DocumentModel(
        sections=sections,
        resources=resources,
        metadata=metadata,
        source_format="pdf",
        mode=ConversionMode.BALANCED,
    )


def _merge_ocr_into_geometry(
    geometry: "PdfGeometryDocument",  # noqa: F821
    ocr_pages: "list[OcrPageResult]",  # noqa: F821
) -> "PdfGeometryDocument":  # noqa: F821
    """Merge OCR results into PDF geometry text blocks per page."""
    from textalchemy.formats.pdf_geometry import (
        PdfGeometryDocument as GeoDoc,
    )
    from textalchemy.formats.pdf_geometry import (
        PdfLineGeometry,
        PdfPageGeometry,
        PdfSpanGeometry,
        PdfTextBlockGeometry,
    )
    from textalchemy.formats.pdf_ocr_merge import _merge_text_layer_and_ocr_page
    from textalchemy.formats.pdf_ocr_types import OcrPageResult

    new_pages: list[PdfPageGeometry] = []
    for page_index, page in enumerate(geometry.pages):
        ocr_page = ocr_pages[page_index] if page_index < len(ocr_pages) else OcrPageResult()

        merged = _merge_text_layer_and_ocr_page(
            list(page.text_blocks),
            list(page.tables),
            ocr_page,
            page.number,
            page.width,
            page.height,
        )

        text_blocks: list[PdfTextBlockGeometry] = []
        for idx, mb in enumerate(merged):
            span = PdfSpanGeometry(
                text=mb.text,
                bbox=mb.bbox,
                origin=(mb.bbox[0], mb.bbox[1]),
            )
            line = PdfLineGeometry(spans=(span,), bbox=mb.bbox)
            text_blocks.append(PdfTextBlockGeometry(lines=(line,), bbox=mb.bbox, number=idx))

        new_pages.append(
            PdfPageGeometry(
                number=page.number,
                width=page.width,
                height=page.height,
                rotation=page.rotation,
                text_blocks=tuple(text_blocks),
                image_blocks=page.image_blocks,
                tables=page.tables,
                extracted_images=page.extracted_images,
                vector_drawings=page.vector_drawings,
            )
        )

    return GeoDoc(
        pages=new_pages,
        metadata=geometry.metadata,
        engine=geometry.engine,
        warnings=list(geometry.warnings),
    )
