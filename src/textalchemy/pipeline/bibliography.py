"""Парсинг библиографии из файла.

Сейчас используется ``organize.bibliography.BibliographyParser.parse_file``.
В перспективе — переехать сюда полностью; пока — тонкая обёртка.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from textalchemy.core.registry import operation
from textalchemy.core.types import BibItem


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
    return BibliographyParser.parse_file(str(p))


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

    return smart_parse(text)


__all__ = ["parse_bibliography", "smart_parse_bibliography"]
