import pytest

from textalchemy.recognize import LayoutAnalyzer


def test_layout_analyzer_init():
    analyzer = LayoutAnalyzer()
    assert analyzer.is_available == analyzer._pil_available


def test_layout_no_file():
    analyzer = LayoutAnalyzer()
    with pytest.raises(Exception):
        analyzer.analyze("nonexistent.png")
