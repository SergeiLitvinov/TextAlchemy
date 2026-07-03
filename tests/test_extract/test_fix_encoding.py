
import pytest

from textalchemy.core.exceptions import ExtractError
from textalchemy.extract.fix_encoding import fix_encoding


def test_fix_encoding_no_file():
    with pytest.raises(ExtractError, match="File not found"):
        fix_encoding("nonexistent.txt")


def test_fix_encoding_utf8(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Hello World", encoding="utf-8")
    result = fix_encoding(f)
    assert "Replaced" in result


def test_fix_encoding_cp1251(tmp_path):
    f = tmp_path / "test.txt"
    f.write_bytes("Привет".encode("cp1251"))
    result = fix_encoding(f)
    assert "Replaced" in result


def test_fix_encoding_replaces_smart_quotes(tmp_path):
    f = tmp_path / "test.txt"
    out = tmp_path / "out.txt"
    text = "\u201cHello\u201d \u2014 world"
    f.write_text(text, encoding="utf-8")
    result = fix_encoding(f, output_path=out)
    assert "Replaced" in result
    fixed = out.read_bytes()
    assert b'"' in fixed


def test_fix_encoding_with_output(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("test \u201cquote\u201d", encoding="utf-8")
    dst = tmp_path / "out" / "fixed.txt"
    result = fix_encoding(src, output_path=dst)
    assert dst.exists()
    assert "Replaced" in result


def test_fix_encoding_replaces_all_variants(tmp_path):
    f = tmp_path / "test.txt"
    text = "\u2014 \u2013 \u2026 \u201c \u201d \u2018 \u2019 \u00ab \u00bb"
    f.write_text(text, encoding="utf-8")
    result = fix_encoding(f)
    assert "Replaced" in result


def test_fix_encoding_non_encodable(tmp_path):
    f = tmp_path / "test.txt"
    f.write_bytes(b"Hello \x80 World")
    result = fix_encoding(f)
    assert isinstance(result, str)
