"""Shared OOXML DrawingML color resolution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from textalchemy.core.color import ColorValue

_COLOR_NODES = frozenset({"srgbClr", "schemeClr", "sysClr"})
_MODIFIERS = {
    "tint": "tint",
    "shade": "shade",
    "lumMod": "luminance_mod",
    "lumOff": "luminance_offset",
    "alpha": "alpha",
}


def resolve_drawingml_color(
    node: Any,
    theme_colors: Mapping[str, str],
) -> tuple[ColorValue | None, dict[str, Any]]:
    """Resolve a DrawingML color container and retain its source metadata."""
    if node is None:
        return None, {}
    color_node = node if _local_name(node.tag) in _COLOR_NODES else next(
        (child for child in node if _local_name(child.tag) in _COLOR_NODES),
        None,
    )
    if color_node is None:
        return None, {}
    kind = _local_name(color_node.tag)
    theme = color_node.get("val") if kind == "schemeClr" else None
    raw = theme_colors.get(theme or "") if theme else color_node.get("val") or color_node.get("lastClr")
    if not raw:
        return None, {}
    try:
        color = ColorValue.from_hex("#" + raw)
    except ValueError:
        return None, {}
    modifiers: dict[str, float] = {}
    for child in color_node:
        target = _MODIFIERS.get(_local_name(child.tag))
        if target and child.get("val") is not None:
            value = max(0.0, min(1.0, float(child.get("val")) / 100000.0))
            modifiers[target] = value
            color = color.transformed(**{target: value})
    properties: dict[str, Any] = {"color_source": kind}
    if theme:
        properties["color_theme"] = theme
    if modifiers:
        properties["color_modifiers"] = modifiers
    return color, properties


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


__all__ = ["resolve_drawingml_color"]
