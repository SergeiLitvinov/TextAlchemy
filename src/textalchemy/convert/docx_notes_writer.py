"""Запись ссылок на сноски в текстовый поток DOCX."""

from __future__ import annotations

from typing import Any

from textalchemy.convert.docx_style_writer import apply_text_style
from textalchemy.core.document_model import TextRun


def write_note_reference(paragraph: Any, item: TextRun) -> bool:
    """Записать footnote/endnote reference; вернуть ``True`` при совпадении."""

    reference_id = item.properties.get("footnote_reference_id")
    element_name = "w:footnoteReference"
    if reference_id is None:
        reference_id = item.properties.get("endnote_reference_id")
        element_name = "w:endnoteReference"
    if reference_id is None:
        return False

    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = paragraph.add_run()
    apply_text_style(run, item.style)
    reference = OxmlElement(element_name)
    reference.set(qn("w:id"), str(reference_id))
    run._r.append(reference)
    return True


__all__ = ["write_note_reference"]
