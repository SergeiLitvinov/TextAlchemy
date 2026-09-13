"""Запись абзацев и строчного содержимого в DOCX."""

from __future__ import annotations

from typing import Any

from textalchemy.convert.docx_drawing_writer import write_image
from textalchemy.convert.docx_notes_writer import write_note_reference
from textalchemy.convert.docx_style_writer import apply_numbering, apply_paragraph_format, apply_text_style
from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import DocumentModel, Formula, FormulaFormat, Image, Paragraph, TextRun
from textalchemy.ooxml.package import RELATIONSHIP_TYPE


def add_paragraph(
    container: Any,
    source: Paragraph,
    document: DocumentModel,
    report: ConversionReport,
    location: str,
) -> Any:
    """Создать и оформить абзац модели в python-docx container."""

    style = source.properties.get("style_name") or source.style_id
    try:
        paragraph = container.add_paragraph(style=style) if style else container.add_paragraph()
    except KeyError:
        paragraph = container.add_paragraph()
        report.add(IssueSeverity.WARNING, "paragraph-style", f"style {style!r} is unavailable", location)
    if source.alignment:
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        alignment = getattr(WD_ALIGN_PARAGRAPH, source.alignment.upper(), None)
        if alignment is not None:
            paragraph.alignment = alignment
    apply_paragraph_format(paragraph.paragraph_format, source.properties)
    preserves_style_numbering = (
        source.properties.get("numbering_source") == "style"
        and source.properties.get("numbering_source_style_id") == source.style_id
        and document.package is not None
        and document.package.related_part(document.package.root, RELATIONSHIP_TYPE["styles"]) is not None
    )
    if not preserves_style_numbering:
        apply_numbering(paragraph._p.get_or_add_pPr(), source.properties)
    if "html_list_id" in source.properties:
        from textalchemy.convert.docx_html_lists import apply_html_list

        apply_html_list(paragraph, source.properties)
    if document.source_format == "html" and source.properties.get("anchor_id"):
        from textalchemy.convert.docx_html_links import add_bookmark

        add_bookmark(paragraph, source.properties["anchor_id"])
    return paragraph


def write_paragraph_content(
    paragraph: Any,
    source: Paragraph,
    document: DocumentModel,
    report: ConversionReport,
    location: str,
    counters: dict[str, int],
) -> None:
    """Записать упорядоченное содержимое абзаца."""

    for index, item in enumerate(source.content):
        item_location = f"{location}.content[{index}]"
        if isinstance(item, TextRun):
            if item.properties.get("docx_raw_inline_xml"):
                _write_raw_inline(paragraph, str(item.properties["docx_raw_inline_xml"]), report, item_location)
            elif item.properties.get("bookmark_start") is not None:
                _write_bookmark_start(paragraph, item.properties["bookmark_start"])
            elif item.properties.get("bookmark_end_id") is not None:
                _write_bookmark_end(paragraph, item.properties["bookmark_end_id"])
            elif write_note_reference(paragraph, item):
                continue
            elif item.properties.get("field_xml"):
                _write_raw_field(paragraph, item.properties["field_xml"])
            elif item.properties.get("field_instruction") is not None:
                _write_simple_field(paragraph, item)
            else:
                run = paragraph.add_run(item.text)
                apply_text_style(run, item.style)
                if item.link and item.link.startswith("#") and document.source_format == "html":
                    from urllib.parse import unquote

                    from textalchemy.convert.docx_html_links import bookmark_name

                    _wrap_internal_hyperlink(paragraph, run, bookmark_name(unquote(item.link[1:])))
                elif item.link:
                    _wrap_hyperlink(paragraph, run, item.link)
                elif item.properties.get("hyperlink_anchor"):
                    _wrap_internal_hyperlink(paragraph, run, str(item.properties["hyperlink_anchor"]))
        elif isinstance(item, Formula):
            write_formula(paragraph, item, report, item_location)
            counters["formulas"] += 1
        elif isinstance(item, Image):
            write_image(paragraph, item, document, report, item_location)
            counters["images"] += 1


def write_formula(paragraph: Any, formula: Formula, report: ConversionReport, location: str) -> None:
    """Записать OMML или диагностированный текстовый fallback."""

    if formula.format is FormulaFormat.MATHML:
        from textalchemy.convert.mathml_to_omml import mathml_to_omml

        try:
            from docx.oxml import parse_xml

            paragraph._p.append(parse_xml(mathml_to_omml(formula.value)))
            return
        except ValueError as error:
            report.add(IssueSeverity.LOSS, "formula", f"MathML fallback: {error}", location)
            paragraph.add_run(formula.fallback_text or formula.value)
            return
    if formula.format is FormulaFormat.OMML:
        from docx.oxml import parse_xml

        try:
            paragraph._p.append(parse_xml(formula.value))
            return
        except Exception as error:  # noqa: BLE001 - malformed foreign XML is reported as a loss
            report.add(IssueSeverity.LOSS, "formula", f"invalid OMML replaced by fallback: {error}", location)
    else:
        report.add(
            IssueSeverity.LOSS,
            "formula",
            f"{formula.format.value} is not natively convertible to OMML; fallback text used",
            location,
        )
    paragraph.add_run(formula.fallback_text or formula.value)


def _wrap_hyperlink(paragraph: Any, run: Any, url: str) -> None:
    from docx.opc.constants import RELATIONSHIP_TYPE as DOCX_RELATIONSHIP_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    relationship_id = paragraph.part.relate_to(url, DOCX_RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)
    run._r.getparent().remove(run._r)
    hyperlink.append(run._r)
    paragraph._p.append(hyperlink)


def _wrap_internal_hyperlink(paragraph: Any, run: Any, anchor: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("w:anchor"), anchor)
    run._r.getparent().remove(run._r)
    hyperlink.append(run._r)
    paragraph._p.append(hyperlink)


def _write_bookmark_start(paragraph: Any, bookmark: dict[str, Any]) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bookmark.get("id") or "0"))
    start.set(qn("w:name"), str(bookmark.get("name") or "_TextAlchemy"))
    paragraph._p.append(start)


def _write_bookmark_end(paragraph: Any, bookmark_id: Any) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bookmark_id))
    paragraph._p.append(end)


def _write_simple_field(paragraph: Any, item: TextRun) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), str(item.properties["field_instruction"]))
    if item.text:
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = item.text
        run.append(text)
        field.append(run)
    paragraph._p.append(field)


def _write_raw_field(paragraph: Any, raw_elements: list[str]) -> None:
    from docx.oxml import parse_xml

    for raw_xml in raw_elements:
        paragraph._p.append(parse_xml(raw_xml))


def _write_raw_inline(paragraph: Any, raw_xml: str, report: ConversionReport, location: str) -> None:
    from docx.oxml import parse_xml

    try:
        paragraph._p.append(parse_xml(raw_xml))
    except Exception as error:  # noqa: BLE001 - foreign OOXML is a diagnostic boundary
        report.add(IssueSeverity.LOSS, "docx-inline-ooxml", f"raw inline OOXML could not be restored: {error}", location)


__all__ = ["add_paragraph", "write_formula", "write_paragraph_content"]
