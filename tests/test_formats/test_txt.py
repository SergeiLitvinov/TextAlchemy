"""Tests for src/textalchemy/formats/txt.py."""

import pytest

from textalchemy.core.types import DocFormat, Text
from textalchemy.formats.txt import read_djvu, read_txt


def test_read_txt(tmp_path):
    p = tmp_path / "test.txt"
    p.write_text("hello world", encoding="utf-8")
    result = read_txt(p)
    assert isinstance(result, Text)
    assert result.plain == "hello world"
    assert result.source_format == DocFormat.TXT


def test_read_txt_missing():
    with pytest.raises(FileNotFoundError):
        read_txt("nonexistent.txt")


def test_read_txt_cp1251(tmp_path):
    p = tmp_path / "cp1251.txt"
    p.write_bytes("привет".encode("cp1251"))
    from opendoc_formats.text_profile import TextProfile

    result = read_txt(p, profile=TextProfile("cp1251"))
    assert "привет" in result.plain


def test_read_djvu_missing():
    with pytest.raises(FileNotFoundError):
        read_djvu("nonexistent.djvu")


def test_read_djvu_no_djvutxt(tmp_path, monkeypatch):
    def missing_tool(*args, **kwargs):
        raise FileNotFoundError("djvutxt")

    monkeypatch.setattr("subprocess.run", missing_tool)
    p = tmp_path / "test.djvu"
    p.write_text("fake", encoding="utf-8")
    result = read_djvu(p)
    assert isinstance(result, Text)
    assert any("djvutxt" in w for w in result.warnings)
