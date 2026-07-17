from textalchemy.formats.pdf import get_pdf_info, read_pdf
from textalchemy.formats.txt import read_djvu, read_txt


def test_read_pdf_no_file():
    result = read_pdf("nonexistent.pdf")
    assert result is not None


def test_get_pdf_info_no_file():
    result = get_pdf_info("nonexistent.pdf")
    assert isinstance(result, dict)


def test_read_docx_no_file():
    from textalchemy.formats.docx import read_docx

    try:
        read_docx("nonexistent.docx")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_read_txt_no_file():
    try:
        read_txt("nonexistent.txt")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_read_djvu_no_file():
    try:
        read_djvu("nonexistent.djvu")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass
