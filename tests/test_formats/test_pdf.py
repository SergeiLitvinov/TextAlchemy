"""Tests for src/textalchemy/formats/pdf.py."""


from textalchemy.core.types import Text
from textalchemy.formats.pdf import get_pdf_info, read_pdf


def test_get_pdf_info_missing():
    info = get_pdf_info("nonexistent.pdf")
    assert info == {"title": "", "author": "", "subject": ""}


def test_read_pdf_missing():
    result = read_pdf("nonexistent.pdf")
    assert isinstance(result, Text)
    assert result.warnings


def test_read_pdf_chain_all_fail(tmp_path):
    p = tmp_path / "corrupt.pdf"
    p.write_text("not a pdf", encoding="utf-8")
    result = read_pdf(str(p))
    assert isinstance(result, Text)
    assert result.plain == ""
    assert any("failed" in w.lower() for w in result.warnings)


def test_get_pdf_info_with_corrupt_file(tmp_path):
    p = tmp_path / "corrupt.pdf"
    p.write_text("garbage", encoding="utf-8")
    info = get_pdf_info(str(p))
    assert info == {"title": "", "author": "", "subject": ""}
