"""Генерация имени файла по ``BibItem``/``Match``.

Перенос ``organize/filename.py::build_filename`` с тем же алгоритмом
аббревиации, но контракт: ``build(BibItem, *, template=...) -> str`` и
``from_match(Match) -> Optional[str]`` (None если матч не сработал).
"""

from __future__ import annotations

import re
from typing import Optional

from textalchemy.core.registry import operation
from textalchemy.core.types import BibItem, Match
from textalchemy.organize.filename import DocType, abbreviate_title, format_authors


def build_filename(
    item: BibItem,
    *,
    template: str = "{index:02d}_{type}_{authors}_{title}",
    max_title_len: int = 55,
    max_authors: int = 3,
    include_type: bool = True,
    ext: str = ".pdf",
    separator: str = "_",
) -> str:
    """Сгенерировать имя файла по ``BibItem``."""
    required = {"index", "type", "authors", "title"}
    found = set(re.findall(r"\{(\w+)(?::[^}]*)?\}", template))
    missing = required - found
    if missing:
        raise ValueError(f"template must contain keys: {missing}")

    authors_str = format_authors(item.authors or [], max_authors)
    title_str = abbreviate_title(item.title, max_title_len)
    type_str = DocType.from_str(item.doc_type).short_rus() if include_type else ""

    if not include_type:
        template = re.sub(r"_?\{type\}?", "", template)

    filename = template.format(
        index=item.index or 0,
        type=type_str,
        authors=authors_str,
        title=title_str,
    )
    filename = re.sub(re.escape(separator) + "+", separator, filename)
    filename = filename.strip(separator).rstrip(".")
    return filename + ext.lower()


@operation(
    "name.from_match",
    input_type="Match",
    output_type="str",
    input_param="match",
    description="Match → имя файла (None если матч не сработал).",
    tags=["name"],
)
def name_from_match(
    *,
    match: Match,
    ext: str = ".pdf",
    template: str = "{index:02d}_{type}_{authors}_{title}",
    require_match: bool = True,
) -> Optional[str]:
    """Сгенерировать имя файла из Match. Возвращает ``None`` если ``require_match=True`` и матча нет."""
    if require_match and (not match.matched or match.item is None):
        return None
    if match.item is None:
        return None
    return build_filename(match.item, template=template, ext=ext)


__all__ = [
    "build_filename",
    "name_from_match",
]
