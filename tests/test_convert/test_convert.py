import pytest

from textalchemy.convert.pdf_to_docx import Pdf2DocxConverter, PyMuPdfConverter, create_converter


def test_create_converter_default():
    conv = create_converter("pdf2docx")
    assert isinstance(conv, Pdf2DocxConverter)


def test_create_converter_pymupdf():
    conv = create_converter("pymupdf")
    assert isinstance(conv, PyMuPdfConverter)


def test_create_converter_unknown():
    with pytest.raises(Exception):
        create_converter("unknown")


def test_convert_nonexistent():
    conv = Pdf2DocxConverter()
    result = conv.convert("nonexistent.pdf", "out.docx")
    assert not result.success
    assert "not found" in (result.error or "").lower()
