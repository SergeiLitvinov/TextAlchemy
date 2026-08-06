"""Тесты анализатора областей изображения (LayoutAnalyzer)."""
from __future__ import annotations

import builtins

import pytest
from PIL import Image

from textalchemy.core.exceptions import RecognizeError
from textalchemy.recognize import LayoutAnalyzer
from textalchemy.recognize.layout import RegionType


def _make_image(tmp_path, name="page.png", width=200, height=100, top_band=False, bottom_band=False):
    img = Image.new("RGB", (width, height), "white")
    if top_band:
        for x in range(width):
            for y in range(int(height * 0.08)):
                img.putpixel((x, y), (0, 0, 0))
    if bottom_band:
        for x in range(width):
            for y in range(int(height * 0.92), height):
                img.putpixel((x, y), (0, 0, 0))
    path = tmp_path / name
    img.save(path)
    return path


def test_layout_analyzer_init():
    analyzer = LayoutAnalyzer()
    assert analyzer.is_available == analyzer._pil_available


def test_layout_no_file():
    analyzer = LayoutAnalyzer()
    with pytest.raises(RecognizeError):
        analyzer.analyze("nonexistent.png")


def test_layout_pil_unavailable(tmp_path, monkeypatch):
    path = _make_image(tmp_path)
    analyzer = LayoutAnalyzer()
    monkeypatch.setattr(analyzer, "_pil_available", False)
    assert analyzer.analyze(path) == []


def test_layout_blank_white_page(tmp_path):
    path = _make_image(tmp_path)
    analyzer = LayoutAnalyzer()
    regions = analyzer.analyze(path)
    types = {r.type for r in regions}
    assert types == {RegionType.TEXT}


def test_layout_detects_header(tmp_path):
    path = _make_image(tmp_path, top_band=True)
    analyzer = LayoutAnalyzer()
    regions = analyzer.analyze(path)
    types = {r.type for r in regions}
    assert RegionType.HEADER in types
    header = next(r for r in regions if r.type == RegionType.HEADER)
    assert header.height == int(100 * 0.08)
    assert header.confidence > 0


def test_layout_detects_footer_and_page_number(tmp_path):
    path = _make_image(tmp_path, bottom_band=True)
    analyzer = LayoutAnalyzer()
    regions = analyzer.analyze(path)
    types = {r.type for r in regions}
    assert RegionType.FOOTER in types
    assert RegionType.PAGE_NUMBER in types


def test_layout_wide_page_two_columns(tmp_path):
    path = _make_image(tmp_path, name="wide.png", width=400, height=200)
    analyzer = LayoutAnalyzer()
    regions = analyzer.analyze(path)
    text_regions = [r for r in regions if r.type == RegionType.TEXT]
    assert len(text_regions) == 2
    assert text_regions[0].x < text_regions[1].x


def test_layout_with_header_and_footer(tmp_path):
    path = _make_image(tmp_path, top_band=True, bottom_band=True)
    analyzer = LayoutAnalyzer()
    regions = analyzer.analyze(path)
    types = {r.type for r in regions}
    assert RegionType.HEADER in types
    assert RegionType.FOOTER in types
    assert RegionType.PAGE_NUMBER in types


def test_layout_numpy_import_failure_fallback(tmp_path, monkeypatch):
    path = _make_image(tmp_path)
    analyzer = LayoutAnalyzer()
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("No module named 'numpy'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    regions = analyzer.analyze(path)
    assert {r.type for r in regions} == {RegionType.TEXT}
