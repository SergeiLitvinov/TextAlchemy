import pytest

from textalchemy.extract import docx_to_latex, extract_text, fix_encoding


def test_extract_text_no_file():
    with pytest.raises(Exception):
        extract_text("nonexistent.docx")


def test_extract_text_wrong_format():
    with pytest.raises(Exception):
        extract_text("test.pdf")


def test_fix_encoding_no_file():
    with pytest.raises(Exception):
        fix_encoding("nonexistent.txt")


def test_docx_to_latex_no_file():
    with pytest.raises(Exception):
        docx_to_latex("nonexistent.docx")


def test_docx_to_latex_wrong_format():
    with pytest.raises(Exception):
        docx_to_latex("test.pdf")
