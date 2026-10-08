"""Tests for src/textalchemy/formats/epub.py."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.corpus.epub_fixture import write_epub_fixture
from textalchemy.core.types import BlockType, DocFormat, Text
from textalchemy.formats.epub import read_epub


def _make_minimal_epub(path: Path) -> None:
    """Создать минимальный EPUB стандартными ZIP/XML средствами."""
    chapter = """
<html><body>
  <h1>Chapter 1</h1>
  <p>Hello world.</p>
  <p>Second paragraph.</p>
  <ul><li>Item A</li><li>Item B</li></ul>
  <h2>Subsection</h2>
  <p>Deeper text.</p>
</body></html>
"""
    write_epub_fixture(path, title="Test EPUB", language="en", chapters=[("chap_1.xhtml", "Chapter 1", chapter)])


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
        assert result.engine == "native-epub+bs4"
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

    def test_returns_text_with_warnings_on_missing_bs4(self, epub_file: Path):
        with patch.dict("sys.modules", {"ebooklib": None, "bs4": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                result = read_epub(epub_file)
        assert isinstance(result, Text)
        assert "beautifulsoup4 not installed" in result.warnings

    def test_import_error_warning_content(self, epub_file: Path):
        with patch.dict("sys.modules", {"ebooklib": None, "bs4": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                result = read_epub(epub_file)
        assert result.plain == ""
        assert result.blocks == []
        assert result.source_format == DocFormat.EPUB
        assert result.engine == "native-epub"

    def test_plain_text_joins_blocks(self, epub_file: Path):
        result = read_epub(epub_file)
        parts = result.plain.split("\n")
        assert len(parts) == len(result.blocks)
        for p, b in zip(parts, result.blocks):
            assert p == b.text
