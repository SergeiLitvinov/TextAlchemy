"""Smoke test: импорт пакета и сборка структуры.

Не требует наличия .pptx — проверяет, что публичный API доступен
и все внутренние модули импортируются без ошибок.
"""

from __future__ import annotations

from pathlib import Path

from textalchemy.convert.pptx_to_html import PptxToHtmlConverter, convert
from textalchemy.convert.pptx_to_html._omml import (
    M_NS,
    MATH_NS_URI,
    has_math,
)
from textalchemy.convert.pptx_to_html._pptx_lib import (
    EMU_PER_INCH,
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
    import opendoc_formats.writers.pptx_to_html as package

    pptx_html = Path(package.__file__).parent
    assert (pptx_html / "assets" / "css" / "main.css").is_file()
    assert (pptx_html / "assets" / "js" / "main.js").is_file()


_CORPUS_PPTX = Path(__file__).resolve().parents[2] / "tests" / "corpus" / "office" / "libreoffice-scientific-slides.pptx"


def test_convert_corpus_pptx(tmp_path):
    """End-to-end: corpus-презентация конвертируется в автономный HTML."""
    output = tmp_path / "out"
    result = PptxToHtmlConverter().convert(_CORPUS_PPTX, output)
    assert result.success is True
    assert result.error is None

    index = output / "index.html"
    assert index.is_file()
    html = index.read_text(encoding="utf-8")
    assert "<html" in html.lower()
    assert "slide" in html.lower()
    assert (output / "assets" / "css" / "main.css").is_file()
    assert (output / "assets" / "js" / "main.js").is_file()


def test_convert_missing_input(tmp_path):
    result = PptxToHtmlConverter().convert(tmp_path / "nope.pptx", tmp_path / "out")
    assert result.success is False
    assert "not found" in result.error


def test_convert_error_is_reported(tmp_path, monkeypatch):
    import textalchemy.convert.pptx_to_html.converter as converter_mod

    def boom(input_path, output_path):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(converter_mod, "_convert_pptx_impl", boom)
    result = PptxToHtmlConverter().convert(_CORPUS_PPTX, tmp_path / "out")
    assert result.success is False
    assert "renderer exploded" in result.error


def test_convert_without_copy_assets_still_succeeds(tmp_path):
    output = tmp_path / "out"
    result = PptxToHtmlConverter(copy_assets=False).convert(_CORPUS_PPTX, output)
    assert result.success is True
    assert (output / "index.html").is_file()


def test_convert_function_wrapper(tmp_path):
    output = tmp_path / "out"
    result = convert(_CORPUS_PPTX, output, copy_assets=False)
    assert result.success is True
    assert (output / "index.html").is_file()
