"""Tests for canonical SVG paint discovery."""

from textalchemy.core.color import ColorValue
from textalchemy.formats.svg_color import parse_svg_color, svg_color_catalog


def test_parse_svg_rgb_and_opacity():
    color = parse_svg_color("rgba(51, 102, 153, 0.5)", opacity=0.5)

    assert color is not None
    assert color.to_hex(include_alpha=True) == "#33669940"


def test_svg_catalog_normalizes_attributes_and_inline_style():
    data = b"""<svg xmlns="http://www.w3.org/2000/svg">
      <rect fill="#336699" fill-opacity="0.5" stroke="rgb(255, 0, 0)"/>
      <path style="fill:#00FF00;stroke:#0000FF;stroke-opacity:25%"/>
    </svg>"""

    catalog = svg_color_catalog(data)
    colors = {(item["element"], item["attribute"]): ColorValue.from_dict(item["color"]) for item in catalog}

    assert colors[("rect", "fill")].to_hex(include_alpha=True) == "#33669980"
    assert colors[("rect", "stroke")].to_hex() == "#FF0000"
    assert colors[("path", "fill")].to_hex() == "#00FF00"
    assert colors[("path", "stroke")].to_hex(include_alpha=True) == "#0000FF40"
