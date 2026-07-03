from textalchemy.organize.extractors.docx import read_docx
from textalchemy.organize.extractors.pdf import get_pdf_info, read_pdf
from textalchemy.organize.extractors.txt import read_djvu, read_txt


def test_read_pdf_no_file():
    result = read_pdf("nonexistent.pdf")
    assert result == ""


def test_get_pdf_info_no_file():
    result = get_pdf_info("nonexistent.pdf")
    assert isinstance(result, dict)


def test_read_docx_no_file():
    result = read_docx("nonexistent.docx")
    assert result == ""


def test_read_txt_no_file():
    result = read_txt("nonexistent.txt")
    assert result == ""


def test_read_djvu_no_file():
    result = read_djvu("nonexistent.djvu")
    assert result == ""
