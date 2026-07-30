"""Чтение абзацев и строчного содержимого DOCX."""

from __future__ import annotations

from typing import Any

from textalchemy.core.document_model import DocumentModel, Formula, FormulaFormat, Image, Paragraph, TextRun
from textalchemy.formats.docx_drawing import read_run_images
from textalchemy.formats.docx_notes import append_note_references
from textalchemy.formats.docx_style import read_paragraph_properties, read_run_style


def read_paragraph(paragraph: Any, model: DocumentModel) -> Paragraph:
    """Преобразовать абзац python-docx в богатую модель."""

    from docx.oxml.ns import qn
    from docx.text.hyperlink import Hyperlink
    from docx.text.run import Run
    from lxml import etree

    content: list[TextRun | Formula | Image] = []
    children = list(paragraph._p.iterchildren())
    index = 0
    while index < len(children):
        child = children[index]
        local_name = etree.QName(child).localname
        if local_name == "r":
            field = _read_complex_field(children, index, paragraph)
            if field is not None:
                field_run, index = field
                content.append(field_run)
                continue
            _append_run_content(content, Run(child, paragraph), paragraph, model)
        elif local_name == "hyperlink":
            hyperlink = Hyperlink(child, paragraph)
            anchor = child.get(qn("w:anchor"))
            for run in hyperlink.runs:
                _append_run_content(content, run, paragraph, model, link=hyperlink.url or None, anchor=anchor)
        elif local_name == "bookmarkStart":
            content.append(
                TextRun(
                    "",
                    properties={
                        "bookmark_start": {
                            "id": child.get(qn("w:id")),
                            "name": child.get(qn("w:name")),
                        }
                    },
                )
            )
        elif local_name == "bookmarkEnd":
            content.append(TextRun("", properties={"bookmark_end_id": child.get(qn("w:id"))}))
        elif local_name in {"oMath", "oMathPara"}:
            content.append(
                Formula(
                    value=etree.tostring(child, encoding="unicode"),
                    format=FormulaFormat.OMML,
                    display=local_name == "oMathPara",
                    fallback_text="".join(child.itertext()),
                )
            )
        elif local_name == "fldSimple":
            content.append(
                TextRun(
                    "".join(child.itertext()),
                    properties={
                        "field_instruction": child.get(qn("w:instr"), "").strip(),
                        "field_xml": [etree.tostring(child, encoding="unicode")],
                    },
                )
            )
        index += 1

    alignment = paragraph.alignment
    return Paragraph(
        content=content,
        style_id=paragraph.style.style_id if paragraph.style is not None else None,
        alignment=alignment.name.lower() if alignment is not None else None,
        properties=read_paragraph_properties(paragraph),
    )


def _append_run_content(
    content: list[TextRun | Formula | Image],
    run: Any,
    paragraph: Any,
    model: DocumentModel,
    *,
    link: str | None = None,
    anchor: str | None = None,
) -> None:
    style = read_run_style(run, paragraph)
    if run.text:
        properties = {"hyperlink_anchor": anchor} if anchor else {}
        content.append(TextRun(run.text, style=style, link=link, properties=properties))
    append_note_references(content, run, style)
    content.extend(read_run_images(run, model))


def _read_complex_field(children: list[Any], start: int, paragraph: Any) -> tuple[TextRun, int] | None:
    from docx.oxml.ns import qn
    from docx.text.run import Run
    from lxml import etree

    first_field_char = children[start].xpath("./w:fldChar")
    if not first_field_char or first_field_char[0].get(qn("w:fldCharType")) != "begin":
        return None
    depth = 0
    separated = False
    instruction_parts: list[str] = []
    result_parts: list[str] = []
    raw_xml: list[str] = []
    result_style = read_run_style(Run(children[start], paragraph), paragraph)
    index = start
    while index < len(children):
        child = children[index]
        raw_xml.append(etree.tostring(child, encoding="unicode"))
        for field_char in child.xpath(".//w:fldChar"):
            field_type = field_char.get(qn("w:fldCharType"))
            if field_type == "begin":
                depth += 1
            elif field_type == "separate" and depth == 1:
                separated = True
            elif field_type == "end":
                depth -= 1
        if not separated:
            instruction_parts.extend(node.text or "" for node in child.xpath(".//w:instrText"))
        elif depth > 0:
            texts = child.xpath(".//w:t")
            if texts and not result_parts:
                result_style = read_run_style(Run(child, paragraph), paragraph)
            result_parts.extend(node.text or "" for node in texts)
        index += 1
        if depth == 0:
            return (
                TextRun(
                    "".join(result_parts),
                    style=result_style,
                    properties={
                        "field_instruction": "".join(instruction_parts).strip(),
                        "field_complex": True,
                        "field_xml": raw_xml,
                    },
                ),
                index,
            )
    return None


__all__ = ["read_paragraph"]
