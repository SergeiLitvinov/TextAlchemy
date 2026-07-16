"""Legacy re-exports from pipeline/name.py + unique build_filename overload.

Most functions are now canonical in ``textalchemy.pipeline.name``.
This module re-exports them for backward compatibility.
"""
from typing import List

from textalchemy.pipeline.name import (
    DocType,
    abbreviate_title,
    format_authors,
    normalize_filename,
    transliterate,
)
from textalchemy.pipeline.name import (
    build_filename as _build_pipeline,
)


def build_filename(
    index: int,
    authors: List[str],
    title: str,
    doc_type: DocType,
    template: str = "{index:02d}_{type}_{authors}_{title}",
    max_title_len: int = 55,
    max_authors: int = 3,
    include_type: bool = True,
    ext: str = ".pdf",
    separator: str = "_",
    transliterate_title: bool = False,
) -> str:
    from textalchemy.core.types import BibItem

    item = BibItem(
        index=index,
        raw_text="",
        authors=list(authors),
        title=title,
        doc_type=doc_type.value if isinstance(doc_type, DocType) else str(doc_type),
    )
    return _build_pipeline(
        item,
        template=template,
        max_title_len=max_title_len,
        max_authors=max_authors,
        include_type=include_type,
        ext=ext,
        separator=separator,
        transliterate_title=transliterate_title,
    )


def extract_authors_from_text(text: str) -> List[str]:
    from textalchemy.organize.bibliography import _extract_authors
    return _extract_authors(text)


def extract_title_from_text(text: str) -> str:
    from textalchemy.organize.bibliography import _extract_title
    return _extract_title(text)


__all__ = [
    "DocType",
    "abbreviate_title",
    "format_authors",
    "build_filename",
    "normalize_filename",
    "transliterate",
    "extract_authors_from_text",
    "extract_title_from_text",
]
