"""Safe SVG color discovery for canonical resource metadata."""

from __future__ import annotations

import re
from xml.etree import ElementTree

from textalchemy.core.color import ColorValue

_COLOR_ATTRIBUTES = frozenset({"fill", "stroke", "stop-color", "flood-color", "lighting-color", "color"})
_CSS_RGB_RE = re.compile(
    r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?))?\s*\)$",
    re.IGNORECASE,
)


def parse_svg_color(value: str, *, opacity: float | None = None) -> ColorValue | None:
    token = value.strip()
    try:
        color = ColorValue.from_hex(token)
    except ValueError:
        match = _CSS_RGB_RE.fullmatch(token)
        if match is None:
            return None
        red, green, blue = (min(255, int(match.group(index))) / 255.0 for index in range(1, 4))
        alpha = float(match.group(4)) if match.group(4) is not None else 1.0
        color = ColorValue.from_srgb_components(red, green, blue, alpha=alpha)
    if opacity is not None:
        color = color.transformed(alpha=color.alpha * max(0.0, min(1.0, opacity)))
    return color


def svg_color_catalog(data: bytes) -> list[dict[str, object]]:
    """Collect explicit SVG paint values without changing the source asset."""
    try:
        root = ElementTree.fromstring(data)
    except (ElementTree.ParseError, UnicodeDecodeError):
        return []
    result: list[dict[str, object]] = []
    for element in root.iter():
        declarations = _style_declarations(element.attrib.get("style", ""))
        for attribute in _COLOR_ATTRIBUTES:
            raw = element.attrib.get(attribute, declarations.get(attribute))
            if not raw:
                continue
            opacity_raw = element.attrib.get(f"{attribute}-opacity") or declarations.get(f"{attribute}-opacity")
            opacity = _opacity(opacity_raw)
            color = parse_svg_color(raw, opacity=opacity)
            if color is not None:
                result.append({"element": _local_name(element.tag), "attribute": attribute, "color": color.to_dict()})
    return result


def _style_declarations(value: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for declaration in value.split(";"):
        name, separator, raw = declaration.partition(":")
        if separator:
            declarations[name.strip().lower()] = raw.strip()
    return declarations


def _opacity(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.strip().removesuffix("%")) / (100.0 if value.strip().endswith("%") else 1.0)
    except ValueError:
        return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


__all__ = ["parse_svg_color", "svg_color_catalog"]
