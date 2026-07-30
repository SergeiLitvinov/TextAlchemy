"""DOCX style resolver for inheritance, themes, defaults, and numbering."""

from __future__ import annotations

from typing import Any

from textalchemy.core.document_model import DocumentModel, Length, TextStyle
from textalchemy.ooxml.package import OOXML_NAMESPACES, RELATIONSHIP_TYPE, package_part_for_relationship


def read_document_styles(document: Any) -> dict[str, TextStyle]:
    from docx.enum.style import WD_STYLE_TYPE

    result: dict[str, TextStyle] = {}
    for style in document.styles:
        if style.type not in {WD_STYLE_TYPE.PARAGRAPH, WD_STYLE_TYPE.CHARACTER}:
            continue
        properties = {
            "style_name": style.name,
            "style_type": style.type.name.lower(),
            "base_style_id": style.base_style.style_id if style.base_style is not None else None,
            "hidden": bool(style.hidden),
            "priority": style.priority,
        }
        if style.type is WD_STYLE_TYPE.PARAGRAPH:
            properties.update(_style_paragraph_properties(style))
            properties.update(_numbering_properties(style.element.pPr))
        result[style.style_id] = _resolved_font_style(style, properties=properties)
    return result


def read_document_defaults(document: Any, model: DocumentModel) -> TextStyle | None:
    from docx.oxml.ns import qn
    from lxml import etree

    run_defaults = document.styles.element.xpath("./w:docDefaults/w:rPrDefault/w:rPr")
    paragraph_defaults = document.styles.element.xpath("./w:docDefaults/w:pPrDefault/w:pPr")
    if not run_defaults and not paragraph_defaults:
        return None
    run_properties = run_defaults[0] if run_defaults else None
    fonts = run_properties.find(qn("w:rFonts")) if run_properties is not None else None
    font_theme = None
    font_family = None
    if fonts is not None:
        font_family = fonts.get(qn("w:ascii")) or fonts.get(qn("w:hAnsi"))
        font_theme = fonts.get(qn("w:asciiTheme")) or fonts.get(qn("w:hAnsiTheme"))
        if font_family is None and font_theme:
            font_family = _theme_typeface(model, font_theme)
    size = run_properties.find(qn("w:sz")) if run_properties is not None else None
    color = run_properties.find(qn("w:color")) if run_properties is not None else None
    color_value = color.get(qn("w:val")) if color is not None else None
    color_theme = color.get(qn("w:themeColor")) if color is not None else None
    if (not color_value or color_value.lower() == "auto") and color_theme:
        color_value = _theme_color(model, color_theme)
    vertical = run_properties.find(qn("w:vertAlign")) if run_properties is not None else None
    vertical_value = vertical.get(qn("w:val")) if vertical is not None else None
    language = run_properties.find(qn("w:lang")) if run_properties is not None else None
    return TextStyle(
        font_family=font_family,
        font_size=Length(int(size.get(qn("w:val"))) / 2) if size is not None and size.get(qn("w:val")) else None,
        bold=_xml_bool(run_properties, "b"),
        italic=_xml_bool(run_properties, "i"),
        underline=_xml_underline(run_properties),
        superscript=True if vertical_value == "superscript" else None,
        subscript=True if vertical_value == "subscript" else None,
        color=f"#{color_value}" if color_value and color_value.lower() != "auto" else None,
        language=language.get(qn("w:val")) if language is not None else None,
        properties={
            "style_name": "Document Defaults",
            "style_type": "document-default",
            "font_theme": font_theme,
            "color_theme": color_theme,
            "paragraph_defaults_xml": (
                etree.tostring(paragraph_defaults[0], encoding="unicode") if paragraph_defaults else None
            ),
        },
    )


def read_run_style(run: Any, paragraph: Any) -> TextStyle:
    sources = [run.font]
    sources.extend(style.font for style in _style_chain(run.style))
    sources.extend(style.font for style in _style_chain(paragraph.style))
    direct_fields = [
        name
        for name in (
            "font_family",
            "font_size",
            "bold",
            "italic",
            "underline",
            "superscript",
            "subscript",
            "color",
            "language",
        )
        if _direct_run_value(run, name) is not None
    ]
    return TextStyle(
        font_family=_first_font_value(sources, "name"),
        font_size=_font_size(_first_font_value(sources, "size")),
        bold=_first_font_value(sources, "bold"),
        italic=_first_font_value(sources, "italic"),
        underline=_underline(_first_font_value(sources, "underline")),
        superscript=_first_font_value(sources, "superscript"),
        subscript=_first_font_value(sources, "subscript"),
        color=_font_color(sources),
        language=_resolved_run_language(run, paragraph),
        properties={
            "style_id": run.style.style_id if run.style is not None else None,
            "style_name": run.style.name if run.style is not None else None,
            "direct_fields": direct_fields,
        },
    )


def read_paragraph_properties(paragraph: Any) -> dict[str, Any]:
    properties = _resolved_paragraph_values(
        [paragraph.paragraph_format, *[style.paragraph_format for style in _style_chain(paragraph.style)]]
    )
    properties.update(_resolved_numbering_properties(paragraph))
    if paragraph.style is not None:
        properties["style_name"] = paragraph.style.name
    return properties


def _theme_typeface(model: DocumentModel, theme_key: str) -> str | None:
    from lxml import etree

    theme = package_part_for_relationship(model.package, RELATIONSHIP_TYPE["theme"])
    if theme is None:
        return None
    root = etree.fromstring(theme.data)
    family = "majorFont" if theme_key.startswith("major") else "minorFont"
    script = "ea" if theme_key.endswith("EastAsia") else "cs" if theme_key.endswith("Bidi") else "latin"
    nodes = root.xpath(
        f"./a:themeElements/a:fontScheme/a:{family}/a:{script}",
        namespaces=OOXML_NAMESPACES,
    )
    return nodes[0].get("typeface") or None if nodes else None


def _theme_color(model: DocumentModel, color_key: str) -> str | None:
    from lxml import etree

    theme = package_part_for_relationship(model.package, RELATIONSHIP_TYPE["theme"])
    if theme is None:
        return None
    root = etree.fromstring(theme.data)
    aliases = {"text1": "dk1", "text2": "dk2", "background1": "lt1", "background2": "lt2"}
    key = aliases.get(color_key, color_key)
    nodes = root.xpath(
        f"./a:themeElements/a:clrScheme/a:{key}/*",
        namespaces=OOXML_NAMESPACES,
    )
    return (nodes[0].get("val") or nodes[0].get("lastClr")) if nodes else None


def _xml_bool(parent: Any, local_name: str) -> bool | None:
    from docx.oxml.ns import qn

    if parent is None:
        return None
    node = parent.find(qn(f"w:{local_name}"))
    if node is None:
        return None
    return str(node.get(qn("w:val"), "1")).lower() not in {"0", "false", "off", "none"}


def _xml_underline(parent: Any) -> bool | None:
    from docx.oxml.ns import qn

    if parent is None:
        return None
    node = parent.find(qn("w:u"))
    if node is None:
        return None
    return str(node.get(qn("w:val"), "single")).lower() not in {"0", "false", "off", "none"}


def _resolved_font_style(style: Any, *, properties: dict[str, Any]) -> TextStyle:
    sources = [item.font for item in _style_chain(style)]
    return TextStyle(
        font_family=_first_font_value(sources, "name"),
        font_size=_font_size(_first_font_value(sources, "size")),
        bold=_first_font_value(sources, "bold"),
        italic=_first_font_value(sources, "italic"),
        underline=_underline(_first_font_value(sources, "underline")),
        superscript=_first_font_value(sources, "superscript"),
        subscript=_first_font_value(sources, "subscript"),
        color=_font_color(sources),
        language=_style_language(style),
        properties=properties,
    )


def _style_chain(style: Any) -> list[Any]:
    result = []
    seen: set[str] = set()
    current = style
    while current is not None and current.style_id not in seen:
        seen.add(current.style_id)
        result.append(current)
        current = current.base_style
    return result


def _first_font_value(sources: list[Any], name: str) -> Any:
    for font in sources:
        value = getattr(font, name)
        if value is not None:
            return value
    return None


def _font_size(value: Any) -> Length | None:
    return Length(float(value.pt)) if value is not None else None


def _underline(value: Any) -> bool | None:
    return bool(value) if value is not None else None


def _font_color(sources: list[Any]) -> str | None:
    for font in sources:
        if font.color is not None and font.color.rgb is not None:
            return f"#{font.color.rgb}"
    return None


def _direct_run_value(run: Any, name: str) -> Any:
    if name == "font_family":
        return run.font.name
    if name == "font_size":
        return run.font.size
    if name == "color":
        return _font_color([run.font])
    if name == "language":
        return _run_language(run)
    return getattr(run.font, name)


def _resolved_run_language(run: Any, paragraph: Any) -> str | None:
    direct = _run_language(run)
    if direct:
        return direct
    for style in [*_style_chain(run.style), *_style_chain(paragraph.style)]:
        language = _style_language(style)
        if language:
            return language
    return None


def _run_language(run: Any) -> str | None:
    from docx.oxml.ns import qn

    language = run._r.xpath("./w:rPr/w:lang")
    return language[0].get(qn("w:val")) if language else None


def _style_language(style: Any) -> str | None:
    from docx.oxml.ns import qn

    for item in _style_chain(style):
        language = item.element.xpath("./w:rPr/w:lang")
        if language:
            return language[0].get(qn("w:val"))
    return None


def _style_paragraph_properties(style: Any) -> dict[str, Any]:
    return _resolved_paragraph_values([item.paragraph_format for item in _style_chain(style)])


def _resolved_paragraph_values(formats: list[Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for name in ("left_indent", "right_indent", "first_line_indent", "space_before", "space_after", "line_spacing"):
        value = next((getattr(item, name) for item in formats if getattr(item, name) is not None), None)
        if hasattr(value, "pt"):
            properties[f"{name}_pt"] = float(value.pt)
        elif value is not None:
            properties[name] = float(value)
    for name in ("keep_together", "keep_with_next", "page_break_before", "widow_control"):
        value = next((getattr(item, name) for item in formats if getattr(item, name) is not None), None)
        if value is not None:
            properties[name] = bool(value)
    return properties


def _resolved_numbering_properties(paragraph: Any) -> dict[str, Any]:
    properties = _numbering_properties(paragraph._p.pPr)
    if properties:
        properties["numbering_source"] = "direct"
        return properties
    for style in _style_chain(paragraph.style):
        properties = _numbering_properties(style.element.pPr)
        if properties:
            properties["numbering_source"] = "style"
            properties["numbering_source_style_id"] = style.style_id
            return properties
    return {}


def _numbering_properties(paragraph_properties: Any) -> dict[str, Any]:
    from docx.oxml.ns import qn

    if paragraph_properties is None:
        return {}
    number_properties = paragraph_properties.find(qn("w:numPr"))
    if number_properties is None:
        return {}
    number_id = number_properties.find(qn("w:numId"))
    level = number_properties.find(qn("w:ilvl"))
    result: dict[str, Any] = {}
    if number_id is not None and number_id.get(qn("w:val")) is not None:
        result["numbering_id"] = int(number_id.get(qn("w:val")))
    if level is not None and level.get(qn("w:val")) is not None:
        result["numbering_level"] = int(level.get(qn("w:val")))
    return result


__all__ = [
    "read_document_defaults",
    "read_document_styles",
    "read_paragraph_properties",
    "read_run_style",
]
