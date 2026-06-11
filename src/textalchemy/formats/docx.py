"""DOCX → Text.

Единый ридер DOCX; раньше было две копии (extract/text.py и
organize/extractors/docx.py).
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from textalchemy.core.types import Block, BlockType, DocFormat, Table, Text


def read_docx(path: Union[str, Path], *, include_tables: bool = True) -> Text:
    from docx import Document  # type: ignore[import-not-found]

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    doc = Document(str(p))
    blocks: list[Block] = []
    tables: list[Table] = []
    plain: list[str] = []

    for para in doc.paragraphs:
        t = para.text
        blocks.append(Block(type=BlockType.PARAGRAPH, text=t))
        if t:
            plain.append(t)

    if include_tables:
        for t in doc.tables:
            rows = [[cell.text for cell in row.cells] for row in t.rows]
            tables.append(Table(rows=rows))
            for row in rows:
                plain.append(" | ".join(row))

    return Text(
        blocks=blocks,
        tables=tables,
        plain="\n".join(plain),
        source_format=DocFormat.DOCX,
        engine="python-docx",
    )


__all__ = ["read_docx"]
