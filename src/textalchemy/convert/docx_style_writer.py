"""DOCX style exporter for definitions, font formatting, and numbering."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import TextStyle


def write_styles(target: Any, styles: dict[str, TextStyle], report: ConversionReport) -> None:
    from docx.enum.style import WD_STYLE_TYPE

    created: dict[str, Any] = {}
    for style_id, source in styles.items():
        properties = source.properties
        if properties.style_type == "document-default":
            continue
        style_name = properties.style_name or style_id
        style_type_name = str(properties.style_type or "paragraph").upper()
        style_type = getattr(WD_STYLE_TYPE, style_type_name, WD_STYLE_TYPE.PARAGRAPH)
        try:
            style = target.styles[style_name]
            if style.type != style_type:
                report.add(
                    IssueSeverity.WARNING,
                    "style-type",
                    f"style {style_name!r} exists with incompatible type {style.type.name.lower()}",
                )
                continue
        except KeyError:
            style = target.styles.add_style(style_name, style_type)
        created[style_id] = style
        apply_font_style(style.font, source)
        _apply_style_language(style, source.language)
        if style_type == WD_STYLE_TYPE.PARAGRAPH:
            apply_paragraph_format(style.paragraph_format, properties)
            apply_numbering(style.element.get_or_add_pPr(), properties)
        if properties.hidden is not None:
            style.hidden = properties.hidden
        if properties.priority is not None:
            style.priority = properties.priority

    for style_id, source in styles.items():
        style = created.get(style_id)
        base_style = created.get(source.properties.base_style_id)
        if style is not None and base_style is not None and style != base_style:
            style.base_style = base_style


def apply_paragraph_format(paragraph_format: Any, properties: Mapping[str, Any]) -> None:
    from docx.shared import Pt

    for name in ("left_indent", "right_indent", "first_line_indent", "space_before", "space_after"):
        value = properties.get(f"{name}_pt")
        if value is not None:
            setattr(paragraph_format, name, Pt(value))
    if properties.get("line_spacing_pt") is not None:
        paragraph_format.line_spacing = Pt(properties["line_spacing_pt"])
    if properties.get("line_spacing") is not None:
        paragraph_format.line_spacing = properties["line_spacing"]
    for name in ("keep_together", "keep_with_next", "page_break_before", "widow_control"):
        if properties.get(name) is not None:
            setattr(paragraph_format, name, bool(properties[name]))


def apply_numbering(paragraph_properties: Any, properties: Mapping[str, Any]) -> None:
    if properties.get("numbering_id") is None:
        return
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    existing = paragraph_properties.find(qn("w:numPr"))
    if existing is not None:
        paragraph_properties.remove(existing)
    number_properties = OxmlElement("w:numPr")
    if properties.get("numbering_level") is not None:
        level = OxmlElement("w:ilvl")
        level.set(qn("w:val"), str(int(properties["numbering_level"])))
        number_properties.append(level)
    number_id = OxmlElement("w:numId")
    number_id.set(qn("w:val"), str(int(properties["numbering_id"])))
    number_properties.append(number_id)
    paragraph_properties.append(number_properties)


def apply_text_style(run: Any, style: TextStyle) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    apply_font_style(run.font, style)
    if style.language:
        run_properties = run._r.get_or_add_rPr()
        language = OxmlElement("w:lang")
        language.set(qn("w:val"), style.language)
        run_properties.append(language)


def apply_font_style(font: Any, style: TextStyle) -> None:
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    from textalchemy.core.color import ColorValue

    if style.font_family:
        font.name = style.font_family
    if style.font_size:
        font.size = Pt(style.font_size.pt)
    font.bold = style.bold
    font.italic = style.italic
    font.underline = style.underline
    font.superscript = style.superscript
    font.subscript = style.subscript
    if style.color:
        color = style.color.to_hex().removeprefix("#") if isinstance(style.color, ColorValue) else style.color.removeprefix("#")
        if len(color) == 6:
            font.color.rgb = RGBColor.from_string(color)
            color_node = font._element.get_or_add_rPr().find(qn("w:color"))
            if color_node is not None and style.properties.get("color_theme"):
                color_node.set(qn("w:themeColor"), str(style.properties["color_theme"]))
                modifiers = style.properties.get("color_modifiers") or {}
                for key, attribute in (("tint", "themeTint"), ("shade", "themeShade")):
                    value = modifiers.get(key)
                    if isinstance(value, (int, float)):
                        color_node.set(qn(f"w:{attribute}"), f"{round(max(0.0, min(1.0, value)) * 255):02X}")


def _apply_style_language(style: Any, language_code: str | None) -> None:
    if not language_code:
        return
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run_properties = style.element.get_or_add_rPr()
    language = OxmlElement("w:lang")
    language.set(qn("w:val"), language_code)
    run_properties.append(language)


__all__ = [
    "apply_font_style",
    "apply_numbering",
    "apply_paragraph_format",
    "apply_text_style",
    "write_styles",
]
