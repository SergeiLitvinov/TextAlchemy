"""Tests for src/textalchemy/formats/epub.py."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from textalchemy.core.types import BlockType, DocFormat, Text
from textalchemy.formats.epub import read_epub


def _make_minimal_epub(path: Path) -> None:
    """Create a minimal valid EPUB at *path* using ebooklib."""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("id-test-001")
    book.set_title("Test EPUB")
    book.set_language("en")

    c1 = epub.EpubHtml(title="Chapter 1", file_name="chap_1.xhtml", lang="en")
    c1.content = """
<html><body>
  <h1>Chapter 1</h1>
  <p>Hello world.</p>
  <p>Second paragraph.</p>
  <ul><li>Item A</li><li>Item B</li></ul>
  <h2>Subsection</h2>
  <p>Deeper text.</p>
</body></html>
"""
    book.add_item(c1)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1]
    epub.write_epub(str(path), book)


@pytest.fixture
def epub_file() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as f:
        tmp = Path(f.name)
    _make_minimal_epub(tmp)
    yield tmp
    tmp.unlink(missing_ok=True)


class TestReadEpub:
    def test_reads_content(self, epub_file: Path):
        result = read_epub(epub_file)
        assert isinstance(result, Text)
        assert result.source_format == DocFormat.EPUB
        assert result.engine == "ebooklib+bs4"
        assert "Hello world." in result.plain
        assert "Chapter 1" in result.plain
        assert "Item A" in result.plain
        assert "Item B" in result.plain
        assert "Subsection" in result.plain
        assert "Deeper text." in result.plain
        assert result.warnings == []

    def test_blocks_are_correct_types(self, epub_file: Path):
        result = read_epub(epub_file)
        heading_blocks = [b for b in result.blocks if b.type == BlockType.HEADING]
        para_blocks = [b for b in result.blocks if b.type == BlockType.PARAGRAPH]
        list_blocks = [b for b in result.blocks if b.type == BlockType.LIST_ITEM]
        assert any(b.level == 1 and b.text == "Chapter 1" for b in heading_blocks)
        assert any(b.level == 2 and b.text == "Subsection" for b in heading_blocks)
        assert any(b.text == "Hello world." for b in para_blocks)
        assert any(b.text == "Second paragraph." for b in para_blocks)
        assert any(b.text == "Deeper text." for b in para_blocks)
        assert any(b.text == "Item A" for b in list_blocks)
        assert any(b.text == "Item B" for b in list_blocks)

    def test_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            read_epub("C:\\nonexistent_file.epub")

    def test_raises_file_not_found_path_object(self):
        with pytest.raises(FileNotFoundError):
            read_epub(Path("C:\\nonexistent_file.epub"))

    def test_returns_text_with_warnings_on_missing_ebooklib(self, epub_file: Path):
        with patch.dict("sys.modules", {"ebooklib": None, "bs4": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                result = read_epub(epub_file)
        assert isinstance(result, Text)
        assert "ebooklib or beautifulsoup4 not installed" in result.warnings

    def test_import_error_warning_content(self, epub_file: Path):
        with patch.dict("sys.modules", {"ebooklib": None, "bs4": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                result = read_epub(epub_file)
        assert result.plain == ""
        assert result.blocks == []
        assert result.source_format == DocFormat.EPUB
        assert result.engine == "ebooklib"

    def test_plain_text_joins_blocks(self, epub_file: Path):
        result = read_epub(epub_file)
        parts = result.plain.split("\n")
        assert len(parts) == len(result.blocks)
        for p, b in zip(parts, result.blocks):
            assert p == b.text
