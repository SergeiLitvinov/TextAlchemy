"""Smoke test: импорт пакета и сборка структуры.

Не требует наличия .pptx — проверяет, что публичный API доступен
и все внутренние модули импортируются без ошибок.
"""
from __future__ import annotations

from textalchemy.convert.pptx_to_html import PptxToHtmlConverter, convert
from textalchemy.convert.pptx_to_html._renderer import (
    convert_pptx,
    render_slide,
    extract_resources,
    extract_title,
)
from textalchemy.convert.pptx_to_html._omml import (
    convert_omml,
    has_math,
    M_NS,
    MATH_NS_URI,
)
from textalchemy.convert.pptx_to_html._pptx_lib import (
    A, NS, O, P, R, V, EMU_PER_INCH,
    PRST_GEOMETRY, THEME_COLORS,
    color_to_hex, emu_to_in, qn, size_to_pt,
)


def test_public_api():
    assert callable(convert)
    assert callable(PptxToHtmlConverter)
    c = PptxToHtmlConverter()
    assert hasattr(c, "convert")


def test_namespace_constants():
    assert M_NS == "http://schemas.openxmlformats.org/officeDocument/2006/math"
    assert MATH_NS_URI == "http://www.w3.org/1998/Math/MathML"
    assert EMU_PER_INCH == 914400


def test_has_math_negative():
    """Пустой <a:p> не должен считаться содержащим формулы."""
    from lxml import etree
    p = etree.Element("{http://schemas.openxmlformats.org/drawingml/2006/main}p")
    assert has_math(p) is False


def test_assets_present():
    """CSS и JS должны быть встроены в пакет."""
    from pathlib import Path
    # tests/convert/test_pptx_to_html.py → parents[2] = TextAlchemy/
    repo_root = Path(__file__).resolve().parents[2]
    pptx_html = repo_root / "src" / "textalchemy" / "convert" / "pptx_to_html"
    assert (pptx_html / "assets" / "css" / "main.css").is_file()
    assert (pptx_html / "assets" / "js" / "main.js").is_file()
