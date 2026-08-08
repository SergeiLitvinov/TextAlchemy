"""Тесты DocumentModel → самодостаточный HTML."""

import pytest
from PIL import Image as PillowImage

from textalchemy.convert.html_writer import write_html_model
from textalchemy.core.diagnostics import IssueSeverity
from textalchemy.core.document_model import (
    Box,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    Length,
    PageSettings,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
)


def _png_bytes(tmp_path):
    path = tmp_path / "picture.png"
    PillowImage.new("RGB", (8, 6), "red").save(path)
    return path.read_bytes()


def test_write_html_model_preserves_styles_tables_images_and_geometry(tmp_path):
    output = tmp_path / "document.html"
    document = DocumentModel(
        metadata={"title": "Rich document", "language": "en"},
        resources={"picture": Resource("picture", ResourceKind.RASTER_IMAGE, "image/png", data=_png_bytes(tmp_path))},
        sections=[
            Section(
                blocks=[
                    Paragraph(
                        content=[
                            TextRun(
                                "Linked & styled",
                                TextStyle(font_family="Arial", font_size=Length(14), bold=True, color="#123456"),
                                link="https://example.com?a=1&b=2",
                            ),
                            Image("picture", alt_text='red "image"', box=Box(0, 0, 72, 54)),
                        ],
                        alignment="center",
                    ),
                    Table(
                        rows=[
                            TableRow(
                                cells=[
                                    TableCell(blocks=[Paragraph(content=[TextRun("wide")])], column_span=2),
                                    TableCell(blocks=[Paragraph(content=[TextRun("tall")])], row_span=2),
                                ]
                            )
                        ]
                    ),
                ]
            )
        ],
    )

    report = write_html_model(document, output)
    html = output.read_text(encoding="utf-8")

    assert report.success is True
    assert report.lossless is True
    assert report.metrics["embedded_resources"] == 1
    assert '<html lang="en">' in html
    assert "Linked &amp; styled" in html
    assert 'href="https://example.com?a=1&amp;b=2"' in html
    assert "font-weight:700" in html
    assert "data:image/png;base64," in html
    assert 'alt="red &quot;image&quot;"' in html
    assert 'colspan="2"' in html
    assert 'rowspan="2"' in html
    assert "@page ta-page-0" in html


def test_write_html_model_preserves_safe_mathml_without_loss(tmp_path):
    output = tmp_path / "formula.html"
    mathml = '<math xmlns="http://www.w3.org/1998/Math/MathML"><msup><mi>x</mi><mn>2</mn></msup></math>'
    document = DocumentModel(sections=[Section(blocks=[Formula(mathml, FormulaFormat.MATHML, display=True)])])

    report = write_html_model(document, output)

    assert report.lossless is True
    assert "<msup>" in output.read_text(encoding="utf-8")


def test_write_html_model_converts_omml_to_mathml(tmp_path):
    output = tmp_path / "omml.html"
    omml = (
        '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        '<m:sSup><m:e><m:r><m:t>x</m:t></m:r></m:e>'
        "<m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup></m:oMath>"
    )
    document = DocumentModel(sections=[Section(blocks=[Formula(omml, FormulaFormat.OMML, fallback_text="x^2")])])

    report = write_html_model(document, output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert "<msup>" in html
    assert "<mi>x</mi>" in html
    assert "<mn>2</mn>" in html
    assert "x^2" not in html


def test_write_html_model_reports_broken_omml(tmp_path):
    output = tmp_path / "broken-omml.html"
    document = DocumentModel(
        sections=[Section(blocks=[Formula("not-a-formula", FormulaFormat.OMML, fallback_text="fallback text")])]
    )

    report = write_html_model(document, output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is False
    assert any(issue.severity is IssueSeverity.LOSS and issue.feature == "formula" for issue in report.issues)
    assert "fallback text" in html


def test_write_html_model_reports_formula_fallback_and_running_header(tmp_path):
    output = tmp_path / "losses.html"
    document = DocumentModel(
        sections=[
            Section(
                blocks=[Formula("E=mc^2", FormulaFormat.LATEX, fallback_text="E = mc²")],
                headers=[Paragraph(content=[TextRun("Header")])],
            )
        ]
    )

    report = write_html_model(document, output)

    assert report.success is True
    assert report.lossless is False
    assert {issue.feature for issue in report.issues if issue.severity is IssueSeverity.LOSS} == {
        "formula",
        "running-header-footer",
    }
    assert "E = mc²" in output.read_text(encoding="utf-8")


def test_write_html_model_sanitizes_unsafe_mathml(tmp_path):
    output = tmp_path / "unsafe.html"
    mathml = '<math xmlns="http://www.w3.org/1998/Math/MathML"><script>alert(1)</script></math>'
    document = DocumentModel(
        sections=[Section(blocks=[Formula(mathml, FormulaFormat.MATHML, fallback_text="safe fallback")])]
    )

    report = write_html_model(document, output)
    html = output.read_text(encoding="utf-8")

    assert report.success is True
    assert report.lossless is False
    assert "<script>" not in html
    assert "safe fallback" in html


def test_write_html_model_rejects_missing_image_resource(tmp_path):
    output = tmp_path / "missing.html"
    document = DocumentModel(sections=[Section(blocks=[Image("missing", alt_text="Missing")])])

    report = write_html_model(document, output)

    assert report.success is False
    assert any(issue.severity is IssueSeverity.ERROR and issue.feature == "image" for issue in report.issues)


def test_write_html_model_renders_pptx_preset_shape_as_svg(tmp_path):
    output = tmp_path / "shape.html"
    paragraph = Paragraph(
        content=[TextRun("Inside the box")],
        box=Box(x=50, y=60, width=180, height=90, rotation=15),
        properties={"pptx": {"shape": {"prst": "roundRect", "fill": "#4472C4", "line": {"color": "#000000", "width": 1.5}}}},
    )
    document = DocumentModel(sections=[Section(blocks=[paragraph])])

    report = write_html_model(document, output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert "position:absolute" in html
    assert "left:50pt" in html
    assert "top:60pt" in html
    assert "width:180pt" in html
    assert "height:90pt" in html
    assert "transform:rotate(15deg)" in html
    assert "background-image:url(&quot;data:image/svg+xml" in html
    assert "fill%3D%22%234472C4%22" in html
    assert "stroke%3D%22%23000000%22" in html


def test_write_html_model_reports_unknown_preset_shape(tmp_path):
    output = tmp_path / "unknown-shape.html"
    paragraph = Paragraph(
        box=Box(x=0, y=0, width=100, height=50),
        properties={"pptx": {"shape": {"prst": "someExoticShape", "fill": "#FF0000"}}},
    )
    document = DocumentModel(sections=[Section(blocks=[paragraph])])

    report = write_html_model(document, output)

    assert report.lossless is False
    assert any(issue.severity is IssueSeverity.LOSS and issue.feature == "preset-shape" for issue in report.issues)
    assert "background-image:url(&quot;data:image/svg+xml" not in output.read_text(encoding="utf-8")


def test_write_html_model_skips_invisible_shape(tmp_path):
    output = tmp_path / "invisible-shape.html"
    paragraph = Paragraph(
        box=Box(x=0, y=0, width=100, height=50),
        properties={"pptx": {"shape": {"prst": "rect", "fill": "none"}}},
    )
    document = DocumentModel(sections=[Section(blocks=[paragraph])])

    report = write_html_model(document, output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert "background-image:url(&quot;data:image/svg+xml" not in html
    assert "position:absolute" in html
    assert "left:0pt" in html
    assert "top:0pt" in html
    assert "width:100pt" in html
    assert "height:50pt" in html


def test_write_html_model_preserves_slide_canvas_and_background(tmp_path):
    output = tmp_path / "slide.html"
    document = DocumentModel(
        sections=[
            Section(
                blocks=[Paragraph(content=[TextRun("Title")], box=Box(x=72, y=36, width=360, height=40))],
                page=PageSettings(
                    width=Length(960),
                    height=Length(540),
                    margin_top=Length(0),
                    margin_right=Length(0),
                    margin_bottom=Length(0),
                    margin_left=Length(0),
                ),
                properties={"background_fill": "#F2F2F2"},
            )
        ]
    )

    report = write_html_model(document, output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert ".ta-section-0 { page: ta-page-0; width: 960pt; min-height: 540pt; padding: 0pt 0pt 0pt 0pt; }" in html
    assert '<section class="ta-section ta-section-0" style="background-color:#F2F2F2">' in html
    assert "left:72pt" in html
    assert "top:36pt" in html


def test_write_html_model_uses_exact_pptx_affine_transform(tmp_path):
    output = tmp_path / "affine.html"
    paragraph = Paragraph(
        content=[TextRun("Transformed")],
        box=Box(x=108, y=36, width=72, height=144, rotation=90),
        properties={
            "pptx": {
                "shape": {"prst": "rect", "fill": "#4472C4"},
                "transform": {
                    "matrix": [0, -2, -2, 0, 180, 180],
                    "width_pt": 72,
                    "height_pt": 36,
                },
            }
        },
    )

    report = write_html_model(DocumentModel(sections=[Section(blocks=[paragraph])]), output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert "width:72pt" in html
    assert "height:36pt" in html
    assert "transform:matrix(0,-2,-2,0,180,180)" in html
    assert "transform-origin:0 0" in html
    assert "transform:rotate(90deg)" not in html


@pytest.mark.parametrize(
    ("chart_type", "marker"),
    [("barChart", "<rect"), ("lineChart", "<polyline"), ("pieChart", "<path")],
)
def test_write_html_model_renders_editable_svg_charts(tmp_path, chart_type, marker):
    output = tmp_path / f"{chart_type}.html"
    paragraph = Paragraph(
        content=[TextRun("text fallback must be hidden")],
        box=Box(x=20, y=20, width=500, height=300),
        properties={
            "pptx": {
                "shape": {"kind": "chart"},
                "chart": {
                    "chart_type": chart_type,
                    "title": "Retention",
                    "categories": ["Text", "Tables"],
                    "series": [{"name": "Quality", "values": [100, 96], "color": "#4472C4"}],
                },
            }
        },
    )

    report = write_html_model(DocumentModel(sections=[Section(blocks=[paragraph])]), output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert '<svg class="ta-chart"' in html
    assert marker in html
    assert "Retention" in html
    assert "Text: 100.0" in html
    assert "text fallback must be hidden" not in html


def test_write_html_model_reports_unsupported_chart_type(tmp_path):
    output = tmp_path / "unsupported-chart.html"
    paragraph = Paragraph(
        content=[TextRun("Accessible fallback")],
        properties={
            "pptx": {
                "shape": {"kind": "chart"},
                "chart": {"chart_type": "surfaceChart", "series": [{"name": "Z", "values": [1]}]},
            }
        },
    )

    report = write_html_model(DocumentModel(sections=[Section(blocks=[paragraph])]), output)

    assert report.lossless is False
    assert any(issue.feature == "chart" and issue.severity is IssueSeverity.LOSS for issue in report.issues)
    assert "Accessible fallback" in output.read_text(encoding="utf-8")


def test_write_html_model_renders_combo_bar_and_line_chart(tmp_path):
    output = tmp_path / "combo-chart.html"
    chart = {
        "chart_type": "barChart",
        "legend": True,
        "categories": ["Text", "Tables"],
        "series": [
            {"name": "Bars", "values": [70, 60], "color": "#4472C4", "chart_type": "barChart"},
            {"name": "Trend", "values": [1, 3], "color": "#ED7D31", "chart_type": "lineChart"},
        ],
    }
    paragraph = _chart_paragraph(chart)

    report = write_html_model(DocumentModel(sections=[Section(blocks=[paragraph])]), output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert '<rect ' in html
    assert '<polyline ' in html
    assert '<circle ' in html
    assert "Bars: 70" in html
    assert "Trend: 1" in html


@pytest.mark.parametrize(
    ("grouping", "bar_direction"),
    [("stacked", "col"), ("percentStacked", "bar")],
)
def test_write_html_model_renders_stacked_bar_charts(tmp_path, grouping, bar_direction):
    output = tmp_path / f"{grouping}-{bar_direction}.html"
    chart = {
        "chart_type": "barChart",
        "grouping": grouping,
        "bar_direction": bar_direction,
        "legend": True,
        "legend_position": "b",
        "category_axis_title": "Document parts",
        "value_axis_title": "Retention, %",
        "categories": ["Text", "Tables"],
        "series": [
            {"name": "Preserved", "values": [70, 60], "color": "#4472C4"},
            {"name": "Recovered", "values": [30, 40], "color": "#ED7D31"},
        ],
    }
    paragraph = Paragraph(
        content=[TextRun("fallback")],
        box=Box(x=10, y=10, width=600, height=350),
        properties={"pptx": {"shape": {"kind": "chart"}, "chart": chart}},
    )

    report = write_html_model(DocumentModel(sections=[Section(blocks=[paragraph])]), output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert "Preserved: 70" in html
    assert "Recovered: 30" in html
    assert "Document parts" in html
    assert "Retention, %" in html
    assert "fallback" not in html


def _chart_paragraph(chart: dict) -> Paragraph:
    return Paragraph(
        content=[TextRun("fallback")],
        box=Box(x=10, y=10, width=600, height=350),
        properties={"pptx": {"shape": {"kind": "chart"}, "chart": chart}},
    )


def test_write_html_model_formats_axis_tick_labels(tmp_path):
    output = tmp_path / "percent.html"
    chart = {
        "chart_type": "barChart",
        "title": "Share",
        "categories": ["A", "B"],
        "series": [{"name": "S", "values": [0.5, 0.75], "color": "#4472C4"}],
        "axes": {"value": {"num_format": "0.0%"}},
    }

    report = write_html_model(DocumentModel(sections=[Section(blocks=[_chart_paragraph(chart)])]), output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert "75.0%" in html
    assert "60.0%" in html
    assert "0.0%" in html


def test_write_html_model_hides_labels_on_hidden_value_axis(tmp_path):
    output = tmp_path / "hidden-axis.html"
    chart = {
        "chart_type": "barChart",
        "title": "No labels",
        "categories": ["A", "B"],
        "series": [{"name": "S", "values": [10, 20], "color": "#4472C4"}],
        "axes": {"value": {"hidden": True, "num_format": "0.0%"}},
    }

    report = write_html_model(DocumentModel(sections=[Section(blocks=[_chart_paragraph(chart)])]), output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert "10.0%" not in html
    assert "0.0%" not in html
    assert '<rect' in html


def test_write_html_model_respects_explicit_axis_range_and_unit(tmp_path):
    output = tmp_path / "range.html"
    chart = {
        "chart_type": "lineChart",
        "title": "Range",
        "categories": ["A", "B", "C"],
        "series": [{"name": "S", "values": [30, 40, 25], "color": "#4472C4"}],
        "axes": {
            "value": {
                "auto_min": False,
                "min": 0.0,
                "auto_max": False,
                "max": 100.0,
                "major_unit": 20.0,
            }
        },
    }

    report = write_html_model(DocumentModel(sections=[Section(blocks=[_chart_paragraph(chart)])]), output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert "100" in html
    assert "80" in html
    assert "20" in html
    # шаг по major_unit не даёт промежуточного деления 90
    assert ">90<" not in html


def test_write_html_model_pie_chart_uses_series_color(tmp_path):
    output = tmp_path / "pie-color.html"
    chart = {
        "chart_type": "pieChart",
        "title": "Donut",
        "categories": ["A", "B"],
        "series": [{"name": "S", "values": [60, 40], "color": "#70AD47"}],
    }

    report = write_html_model(DocumentModel(sections=[Section(blocks=[_chart_paragraph(chart)])]), output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert '#70AD47' in html


def test_write_html_model_renders_bar_data_labels(tmp_path):
    output = tmp_path / "bar-labels.html"
    chart = {
        "chart_type": "barChart",
        "title": "Labels",
        "categories": ["A", "B"],
        "series": [{"name": "S", "values": [12.5, 7], "color": "#4472C4"}],
        "data_labels": {"show_value": True, "num_format": "0.0"},
    }

    report = write_html_model(DocumentModel(sections=[Section(blocks=[_chart_paragraph(chart)])]), output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert "12.5" in html
    assert "7.0" in html


def test_write_html_model_renders_pie_percent_labels_centered(tmp_path):
    output = tmp_path / "pie-percent.html"
    chart = {
        "chart_type": "pieChart",
        "title": "Share",
        "categories": ["A", "B"],
        "series": [{"name": "S", "values": [75, 25], "color": "#4472C4"}],
        "data_labels": {"show_percent": True, "position": "ctr"},
    }

    report = write_html_model(DocumentModel(sections=[Section(blocks=[_chart_paragraph(chart)])]), output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert "75.0%" in html
    assert "25.0%" in html
    assert 'fill="white"' in html


def test_write_html_model_renders_stacked_percent_data_labels(tmp_path):
    output = tmp_path / "stacked-labels.html"
    chart = {
        "chart_type": "barChart",
        "grouping": "percentStacked",
        "title": "Mix",
        "categories": ["A"],
        "series": [
            {"name": "X", "values": [70], "color": "#4472C4"},
            {"name": "Y", "values": [30], "color": "#ED7D31"},
        ],
        "data_labels": {"show_percent": True},
    }

    report = write_html_model(DocumentModel(sections=[Section(blocks=[_chart_paragraph(chart)])]), output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    assert "70.0%" in html
    assert "30.0%" in html


def test_write_html_model_honors_gap_width_and_overlap(tmp_path):
    output = tmp_path / "gap-overlap.html"
    chart = {
        "chart_type": "barChart",
        "title": "Spacing",
        "categories": ["A"],
        "series": [
            {"name": "X", "values": [10], "color": "#4472C4"},
            {"name": "Y", "values": [20], "color": "#ED7D31"},
        ],
        "gap_width": 50.0,
        "overlap": -27.0,
    }

    report = write_html_model(DocumentModel(sections=[Section(blocks=[_chart_paragraph(chart)])]), output)
    html = output.read_text(encoding="utf-8")

    assert report.lossless is True
    # gap 50% → бары шире, чем при 150%: ширина бара 260, шаг с учётом overlap −27%
    assert 'width="260"' in html
    assert 'x="94.9"' in html
    assert 'x="425.1"' in html
