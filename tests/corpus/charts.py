"""Воспроизводимый корпус диаграмм: rich chart DocumentModels и golden references.

Каждая диаграмма — отдельная секция DocumentModel, которая рендерится в PDF через
``textalchemy.convert.pdf_writer`` (fitz.Story) и затем в PNG через
``textalchemy.quality.visual.render_pdf_pages``. Golden-изображения и manifest
хранятся в ``tests/corpus/visual/charts/``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from textalchemy.convert.pdf_writer import write_pdf_model
from textalchemy.core.document_model import Box, DocumentModel, Paragraph, Section, TextRun
from textalchemy.quality.visual import render_pdf_pages

CHARTS_DIR = Path(__file__).parents[1] / "corpus" / "visual" / "charts"
PAGE_DPI = 96
NORMALISED_SIZE = [160, 160]
THRESHOLDS = {"min_similarity": 0.90, "max_hash_distance": 24, "min_foreground_iou": 0.30}

CHART_BOX = Box(x=72, y=72, width=451, height=400)


def chart_corpus() -> list[tuple[str, dict[str, Any]]]:
    """Именованные chart fixtures, покрывающие богатые фичи рендера."""
    bar_series = [
        {"name": "Series A", "values": [12, 28, 19], "color": "#4472C4"},
        {"name": "Series B", "values": [9, 21, 26], "color": "#ED7D31"},
    ]
    return [
        (
            "bar-clustered",
            {
                "chart_type": "barChart",
                "grouping": "clustered",
                "title": "Clustered bars",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": bar_series,
            },
        ),
        (
            "bar-horizontal",
            {
                "chart_type": "barChart",
                "grouping": "clustered",
                "bar_direction": "bar",
                "title": "Horizontal bars",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": [{"name": "Series A", "values": [12, 28, 19], "color": "#70AD47"}],
            },
        ),
        (
            "bar-stacked",
            {
                "chart_type": "barChart",
                "grouping": "stacked",
                "title": "Stacked bars",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": bar_series,
            },
        ),
        (
            "bar-percent",
            {
                "chart_type": "barChart",
                "grouping": "percentStacked",
                "title": "Percent stacked bars",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": bar_series,
            },
        ),
        (
            "line-markers",
            {
                "chart_type": "lineChart",
                "grouping": "standard",
                "title": "Line with markers",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": [
                    {"name": "Series A", "values": [12, 28, 19], "color": "#4472C4"},
                    {"name": "Series B", "values": [9, 21, 26], "color": "#C00000"},
                ],
            },
        ),
        (
            "pie",
            {
                "chart_type": "pieChart",
                "title": "Pie share",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": [{"name": "Share", "values": [34, 41, 25], "color": "#4472C4"}],
            },
        ),
        (
            "doughnut",
            {
                "chart_type": "doughnutChart",
                "title": "Doughnut share",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": [{"name": "Share", "values": [34, 41, 25], "color": "#ED7D31"}],
            },
        ),
        (
            "combo",
            {
                "chart_type": "barChart",
                "grouping": "clustered",
                "title": "Bar and line combo",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": [
                    {"name": "Bars", "values": [12, 28, 19], "color": "#4472C4"},
                    {"name": "Trend", "values": [30, 22, 35], "color": "#C00000", "chart_type": "lineChart"},
                ],
            },
        ),
        (
            "dual-axis",
            {
                "chart_type": "barChart",
                "grouping": "clustered",
                "title": "Dual value axes",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": [
                    {"name": "Volume", "values": [120, 280, 190], "color": "#4472C4"},
                    {"name": "Growth %", "values": [8, 22, 14], "color": "#ED7D31", "axis": "secondary_value"},
                ],
                "secondary_value_axis_title": "Growth %",
            },
        ),
        (
            "trendline-linear",
            {
                "chart_type": "lineChart",
                "grouping": "standard",
                "title": "Linear trendline",
                "categories": ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"],
                "series": [
                    {
                        "name": "Series A",
                        "values": [8, 14, 13, 21, 24],
                        "color": "#4472C4",
                        "trendline": {
                            "type": "linear",
                            "color": "#C00000",
                            "show_equation": True,
                            "show_r_squared": True,
                        },
                    }
                ],
            },
        ),
        (
            "trendline-moving-avg",
            {
                "chart_type": "barChart",
                "grouping": "clustered",
                "title": "Moving average trendline",
                "categories": ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"],
                "series": [
                    {
                        "name": "Series A",
                        "values": [8, 14, 13, 21, 24],
                        "color": "#4472C4",
                        "trendline": {"type": "movingAvg", "period": 2, "color": "#C00000"},
                    }
                ],
            },
        ),
        (
            "error-bars",
            {
                "chart_type": "barChart",
                "grouping": "clustered",
                "title": "Error bars",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": [
                    {
                        "name": "Series A",
                        "values": [12, 28, 19],
                        "color": "#4472C4",
                        "error_bars": {"direction": "y", "bar_type": "both", "value_type": "fixedVal", "value": 4.0},
                    }
                ],
            },
        ),
        (
            "per-point-colors",
            {
                "chart_type": "barChart",
                "grouping": "clustered",
                "title": "Per-point colors",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": [
                    {
                        "name": "Series A",
                        "values": [12, 28, 19],
                        "color": "#4472C4",
                        "data_points": {0: {"color": "#70AD47"}, 2: {"color": "#C00000"}},
                    }
                ],
            },
        ),
        (
            "data-labels",
            {
                "chart_type": "barChart",
                "grouping": "clustered",
                "title": "Percent data labels",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": [
                    {"name": "Series A", "values": [0.12, 0.28, 0.19], "color": "#4472C4"},
                ],
                "data_labels": {"show": True, "num_format": "0.0%"},
                "axes": {"value": {"num_format": "0%"}},
            },
        ),
        (
            "bar-3d",
            {
                "chart_type": "barChart",
                "chart_3d": True,
                "chart_3d_type": "bar3DChart",
                "grouping": "clustered",
                "title": "3D bars",
                "categories": ["Alpha", "Beta", "Gamma"],
                "view3d": {"rot_x": 15.0, "rot_y": 20.0, "right_angle_axes": True, "perspective": 30.0, "depth_percent": 130.0},
                "series": bar_series,
            },
        ),
        (
            "bar-3d-stacked",
            {
                "chart_type": "barChart",
                "chart_3d": True,
                "chart_3d_type": "bar3DChart",
                "grouping": "stacked",
                "title": "3D stacked bars",
                "categories": ["Alpha", "Beta", "Gamma"],
                "view3d": {"depth_percent": 150.0},
                "series": bar_series,
            },
        ),
        (
            "pie-3d",
            {
                "chart_type": "pieChart",
                "chart_3d": True,
                "chart_3d_type": "pie3DChart",
                "title": "3D pie share",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": [{"name": "Share", "values": [34, 41, 25], "color": "#4472C4"}],
            },
        ),
        (
            "doughnut-3d",
            {
                "chart_type": "doughnutChart",
                "chart_3d": True,
                "chart_3d_type": "doughnut3DChart",
                "title": "3D doughnut share",
                "categories": ["Alpha", "Beta", "Gamma"],
                "series": [{"name": "Share", "values": [34, 41, 25], "color": "#ED7D31"}],
            },
        ),
    ]


def build_chart_document() -> DocumentModel:
    """Собрать DocumentModel: одна секция на диаграмму."""
    sections = []
    for _name, chart in chart_corpus():
        paragraph = Paragraph(
            content=[TextRun("chart")],
            box=CHART_BOX,
            properties={"pptx": {"shape": {"kind": "chart"}, "chart": chart}},
        )
        sections.append(Section(blocks=[paragraph]))
    return DocumentModel(sections=sections, source_format="pptx")


def write_chart_pdf(output: str | Path) -> Path:
    """Записать корпус диаграмм в PDF и вернуть путь."""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = write_pdf_model(build_chart_document(), path)
    if any(issue.severity.name == "ERROR" for issue in report.issues):
        raise RuntimeError(f"chart corpus PDF failed: {[issue.message for issue in report.issues]}")
    return path


def build_golden_charts(output_dir: str | Path = CHARTS_DIR, *, dpi: int = PAGE_DPI) -> list[Path]:
    """Перегенерировать golden PNG и manifest.json для визуальной регрессии диаграмм."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    pdf = write_chart_pdf(target / "chart-corpus.pdf")
    pages = render_pdf_pages(pdf, dpi=dpi)
    names = [name for name, _chart in chart_corpus()]
    if len(pages) != len(names):
        raise RuntimeError(f"expected {len(names)} pages, got {len(pages)}")
    written: list[Path] = []
    entries = []
    for (name, _chart), page in zip(chart_corpus(), pages, strict=True):
        output = target / f"{name}.png"
        page.save(output, format="PNG")
        written.append(output)
        entries.append(
            {
                "name": name,
                "file": output.name,
                "width": page.width,
                "height": page.height,
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "source": "tests.corpus.charts:build_chart_document",
        "renderer": "PyMuPDF Story",
        "dpi": dpi,
        "normalised_size": NORMALISED_SIZE,
        "thresholds": THRESHOLDS,
        "pages": entries,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return written


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


__all__ = ["build_chart_document", "build_golden_charts", "chart_corpus", "sha256", "write_chart_pdf"]

if __name__ == "__main__":
    for artifact in build_golden_charts():
        print(f"{artifact.name}: {artifact.stat().st_size} bytes ({sha256(artifact)[:12]})")
