"""Парсинг библиографии из файла.

Сейчас используется ``organize.bibliography.BibliographyParser.parse_file``.
В перспективе — переехать сюда полностью; пока — тонкая обёртка.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from textalchemy.core.registry import operation
from textalchemy.core.types import BibItem
from textalchemy.organize.bibliography import BibItem as LegacyBibItem


def _to_core(legacy: LegacyBibItem) -> BibItem:
    return BibItem(
        index=legacy.index,
        raw_text=legacy.raw_text,
        authors=list(legacy.authors),
        title=legacy.title,
        year=legacy.year,
        doc_type=legacy.doc_type,
        source=legacy.source,
        pages=legacy.pages,
        doi=legacy.doi,
        isbn=legacy.isbn,
        url=legacy.url,
        journal=legacy.journal,
        publisher=legacy.publisher,
        city=legacy.city,
    )


@operation(
    "bibliography.parse",
    input_type="path",
    output_type="list[BibItem]",
    input_param="path",
    description="Распарсить файл библиографии (.txt) в список BibItem.",
    tags=["bibliography"],
)
def parse_bibliography(*, path: Union[str, Path]) -> list[BibItem]:
    from textalchemy.organize.bibliography import BibliographyParser

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    return [_to_core(b) for b in BibliographyParser.parse_file(str(p))]


@operation(
    "bibliography.smart_parse",
    input_type="text",
    output_type="list[BibItem]",
    input_param="text",
    description="Распарсить произвольный текст в список BibItem (auto-detect формата).",
    tags=["bibliography"],
)
def smart_parse_bibliography(*, text: str) -> list[BibItem]:
    from textalchemy.organize.bibliography import smart_parse

    return [_to_core(b) for b in smart_parse(text)]


__all__ = ["parse_bibliography", "smart_parse_bibliography"]
