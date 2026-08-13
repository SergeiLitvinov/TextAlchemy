"""Tests for shared DrawingML color resolution."""

from lxml import etree

from textalchemy.ooxml.color import resolve_drawingml_color


def test_resolve_drawingml_color_uses_theme_and_ordered_modifiers():
    node = etree.fromstring(
        b'<a:solidFill xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        b'<a:schemeClr val="accent1"><a:shade val="50000"/><a:tint val="50000"/><a:alpha val="25000"/></a:schemeClr>'
        b"</a:solidFill>"
    )

    color, metadata = resolve_drawingml_color(node, {"accent1": "204060"})

    assert color is not None
    assert color.to_hex(include_alpha=True) == "#88909840"
    assert metadata["color_theme"] == "accent1"
