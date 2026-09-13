"""Материализация ссылок на шрифты темы в текстовых фрагментах PPTX."""

from __future__ import annotations

from typing import Any

from textalchemy.core.document_model import Paragraph, Table, TextRun

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _related(part: Any, relationship: str) -> Any:
    try:
        return part.part_related_by(relationship)
    except (KeyError, ValueError, AttributeError):
        return None


def _font_scheme(part: Any) -> dict[str, str] | None:
    from lxml import etree

    if part is None:
        return None
    try:
        root = etree.fromstring(part.blob, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    except (etree.XMLSyntaxError, ValueError):
        return None
    scheme = root.find(".//" + A + "fontScheme")
    if scheme is None:
        return None
    result = {}
    for family, prefix in (("majorFont", "+mj"), ("minorFont", "+mn")):
        for tag, suffix in (("latin", "lt"), ("ea", "ea"), ("cs", "cs")):
            font = scheme.find(f"{A}{family}/{A}{tag}")
            if font is not None and (name := font.get("typeface")):
                result[f"{prefix}-{suffix}"] = name
    return result


def slide_theme_fonts(slide: Any) -> dict[str, str]:
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT

    layout = slide.slide_layout
    master = layout.slide_master
    theme = _related(master.part, RT.THEME)
    if theme is None:
        theme = _related(slide.part.package.main_document_part, RT.THEME)
    result = _font_scheme(theme) or {}
    for part in (layout.part, slide.part):
        override = _font_scheme(_related(part, RT.THEME_OVERRIDE))
        if override is not None:
            result = override
    return result


def materialize_theme_fonts(blocks: list[Any], fonts: dict[str, str]) -> None:
    for block in blocks:
        if isinstance(block, Table):
            for row in block.rows:
                for cell in row.cells:
                    materialize_theme_fonts(cell.blocks, fonts)
        elif isinstance(block, Paragraph):
            for item in block.content:
                if isinstance(item, TextRun) and item.style.font_family in fonts:
                    item.style.font_family = fonts[item.style.font_family]
            for paragraph in block.properties.get("pptx", {}).get("paragraphs", []):
                if paragraph.get("bullet_font") in fonts:
                    paragraph["bullet_font"] = fonts[paragraph["bullet_font"]]
