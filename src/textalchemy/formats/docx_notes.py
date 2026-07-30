"""Чтение ссылок на сноски из текстовых runs DOCX."""

from __future__ import annotations

from typing import Any

from textalchemy.core.document_model import TextRun, TextStyle


def append_note_references(content: list[Any], run: Any, style: TextStyle) -> None:
    """Добавить footnote/endnote references из ``run`` в поток абзаца."""

    from docx.oxml.ns import qn

    for reference in run._r.xpath(".//w:footnoteReference"):
        content.append(
            TextRun(
                "",
                style=style,
                properties={
                    "footnote_reference_id": reference.get(qn("w:id")),
                    "part_name": "/word/footnotes.xml",
                },
            )
        )
    for reference in run._r.xpath(".//w:endnoteReference"):
        content.append(
            TextRun(
                "",
                style=style,
                properties={
                    "endnote_reference_id": reference.get(qn("w:id")),
                    "part_name": "/word/endnotes.xml",
                },
            )
        )


__all__ = ["append_note_references"]
