"""Numerical expectations and honest fallback for the defects found in the TODO audit."""

import xml.etree.ElementTree as ET

import pytest

from textalchemy.convert.html_writer import _error_bar_parts, _trendline_parts, write_html_model
from textalchemy.core.document_model import DocumentModel, Paragraph, Section


@pytest.mark.parametrize("multiplier,expected", [(0, (100, 100)), (1, (90, 110)), (3, (70, 130))])
def test_standard_deviation_multiplier_changes_svg_endpoints(multiplier, expected):
    # Mean=2, population variance=((1-2)^2+(3-2)^2)/2=1.
    # Axis spans 10 units across 100 pixels: one deviation occupies 10 pixels.
    item = {"values": [1, 3], "color": "#123456", "error_bars": {"value_type": "stdDev", "value": multiplier}}
    parts = _error_bar_parts(item, 0, 1, 20, 100, minimum=0, maximum=10, top=0, height=100)
    line = ET.fromstring(parts[0])
    assert (float(line.attrib["y1"]), float(line.attrib["y2"])) == pytest.approx(expected)


def test_linear_trend_coordinates_have_independent_numerical_expectations():
    # Exact y=2*x+2 at category indices 0,1,2; y=2 and 6 map to pixels 80 and 40.
    parts = _trendline_parts(
        {"values": [2, 4, 6], "color": "#123456", "trendline": {"type": "linear"}},
        ["A", "B", "C"], left=10, top=0, width=100, height=100, axis_style={"minimum": 0, "maximum": 10},
    )
    line = ET.fromstring(parts[0])
    assert tuple(float(line.attrib[key]) for key in ("x1", "y1", "x2", "y2")) == pytest.approx((10, 80, 110, 40))


@pytest.mark.parametrize("kind", ["log", "power", "unknown"])
@pytest.mark.parametrize("mixed", [False, True])
def test_unsupported_trend_is_omitted_and_reported_in_full_export(tmp_path, kind, mixed):
    trend = {"type": kind}
    chart = {
        "chart_type": "lineChart", "categories": ["A", "B", "C"],
        "series": [{"values": [2, 4, 9], "trendline": [trend, {"type": "linear"}] if mixed else trend}],
    }
    model = DocumentModel(sections=[Section(blocks=[Paragraph(properties={"pptx": {"chart": chart}})])])
    output = tmp_path / "chart.html"
    report = write_html_model(model, output)
    assert report.success and not report.lossless
    issues = [issue for issue in report.issues if issue.feature == "chart-trendline"]
    assert len(issues) == 1 and kind in issues[0].message
    html = output.read_text(encoding="utf-8")
    assert "<polyline " in html  # Original data series remains visible.
    assert html.count('stroke-dasharray="6 4"') == int(mixed)
