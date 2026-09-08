"""EPUB → Text.

Использует ``ebooklib`` для извлечения текстового содержимого из EPUB-файла.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

from textalchemy.core.io import check_archive_safety
from textalchemy.core.types import Block, BlockType, DocFormat, Text


def read_epub(path: Union[str, Path]) -> Text:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    check_archive_safety(p)
    try:
        import ebooklib
        from bs4 import BeautifulSoup
    except ImportError:
        return Text(
            source_format=DocFormat.EPUB,
            engine="ebooklib",
            warnings=["ebooklib or beautifulsoup4 not installed"],
        )

    from ebooklib import epub

    book = epub.read_epub(str(p))
    blocks: list[Block] = []
    plain_parts: list[str] = []

    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.get_body_content(), "html.parser")
            for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"]):
                text = tag.get_text(strip=True)
                if not text:
                    continue
                tag_name = tag.name.lower()
                if tag_name.startswith("h"):
                    level = int(tag_name[1])
                    btype = BlockType.HEADING
                elif tag_name == "li":
                    level = 0
                    btype = BlockType.LIST_ITEM
                else:
                    level = 0
                    btype = BlockType.PARAGRAPH
                blocks.append(Block(type=btype, text=text, level=level))
                plain_parts.append(text)

    return Text(
        blocks=blocks,
        plain="\n".join(plain_parts),
        source_format=DocFormat.EPUB,
        engine="ebooklib+bs4",
        pages=len(blocks),
    )


def read_epub_model(path: Union[str, Path]):
    """Import EPUB spine chapters, links, media, and basic CSS into DocumentModel."""
    from textalchemy.formats.epub_model import read_epub_model as read_model

    return read_model(path)


__all__ = ["read_epub", "read_epub_model"]
