"""Универсальный ридер: Document → Text.

Выбирает движок по ``Document.format``. Сейчас PDF идёт по цепочке
``pdfplumber → pypdf → pymupdf geometry → semantics`` (см. formats/pdf.py).
"""

from __future__ import annotations

from textalchemy.core.document_model import (
    ConversionMode,
    DocumentModel,
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
    if doc.format == DocFormat.HTML:
        from textalchemy.formats.html import read_html

        return read_html(doc.path)
    if doc.format == DocFormat.EPUB:
        from textalchemy.formats.epub import read_epub

        return read_epub(doc.path)
    return Text(
        source_format=doc.format,
        engine="none",
        warnings=[f"no reader for format {doc.format.value!r}"],
    )


__all__ = ["extract_text", "extract_pdf_model", "extract_pptx_model", "extract_epub_model", "extract_html_model"]


@operation(
    "extract.html_model",
    input_type="Document",
    output_type="DocumentModel",
    input_param="doc",
    description="Статический HTML → DocumentModel; ограничения в metadata.html.warnings.",
    tags=["extract", "html", "document-model"],
)
def extract_html_model(*, doc: Document) -> DocumentModel:
    from textalchemy.formats.html import read_html_model

    if doc.format is not DocFormat.HTML:
        raise ValueError("extract.html_model requires an HTML document")
    return read_html_model(doc.path)


@operation(
    "extract.epub_model",
    input_type="Document",
    output_type="DocumentModel",
    input_param="doc",
    description="EPUB → DocumentModel (главы, ссылки, изображения и базовое CSS).",
    tags=["extract", "epub", "document-model"],
)
def extract_epub_model(*, doc: Document) -> DocumentModel:
    from textalchemy.formats.epub import read_epub_model

    if doc.format is not DocFormat.EPUB:
        raise ValueError("extract.epub_model requires an EPUB document")
    return read_epub_model(doc.path)


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
    mode: str | None = None,
) -> DocumentModel:
    from opendoc_formats.readers.pdf_model import read_pdf_model

    if doc.format != DocFormat.PDF:
        return DocumentModel(
            sections=[],
            source_format=doc.format.value,
            metadata={"engine": "none", "warnings": [f"extract.pdf_model: not a PDF: {doc.format.value!r}"]},
        )
    from textalchemy.recognize.ocr import OcrEngine

    return read_pdf_model(
        path=doc.path,
        use_ocr=use_ocr,
        ocr_backend=ocr_backend,
        handwriting=handwriting,
        use_gpu=use_gpu,
        mode=mode,
        ocr_engine_factory=OcrEngine,
    )


@operation(
    "extract.pptx_model",
    input_type="Document",
    output_type="DocumentModel",
    input_param="doc",
    description="PPTX → DocumentModel (слайды, фигуры, таблицы, изображения, диаграммы, формулы).",
    tags=["extract", "pptx", "document-model"],
)
def extract_pptx_model(
    *,
    doc: Document,
    mode: ConversionMode = ConversionMode.BALANCED,
) -> DocumentModel:
    """Импортировать PPTX в богатую модель через ``read_pptx_model``.

    Args:
        doc: Документ PPTX.
        mode: Режим конвертации (editable/faithful/balanced).

    Returns:
        ``DocumentModel`` со слайдами в качестве секций.
    """
    if doc.format != DocFormat.PPTX:
        return DocumentModel(
            sections=[],
            source_format=doc.format.value,
            metadata={"engine": "none", "warnings": [f"extract.pptx_model: not a PPTX: {doc.format.value!r}"]},
        )

    from textalchemy.formats.pptx import read_pptx_model

    return read_pptx_model(doc.path, mode=mode)
