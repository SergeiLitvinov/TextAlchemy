"""Универсальный ридер: Document → Text.

Выбирает движок по ``Document.format``. Сейчас PDF идёт по цепочке
``pdfplumber → pypdf → pymupdf`` (см. formats/pdf.py).
"""
from __future__ import annotations

from textalchemy.core.registry import operation
from textalchemy.core.types import DocFormat, Document, Text


@operation(
    "extract.text",
    input_type="Document",
    output_type="Text",
    description="Document → Text (универсальный ридер по формату).",
    tags=["extract"],
)
def extract_text(doc: Document) -> Text:
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
    return Text(
        source_format=doc.format,
        engine="none",
        warnings=[f"no reader for format {doc.format.value!r}"],
    )


__all__ = ["extract_text"]
