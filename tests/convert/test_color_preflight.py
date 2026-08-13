"""Tests for target-specific canonical color diagnostics."""

from pathlib import Path

from textalchemy.convert.color_preflight import preflight_colors
from textalchemy.core.color import ColorValue
from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import DocumentModel, Paragraph, Section, TextRun, TextStyle


def _document() -> DocumentModel:
    color = ColorValue.from_hex("#336699", icc_profile="press.icc", blend_mode="multiply")
    return DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun("x", TextStyle(color=color))])])])


def test_docx_reports_icc_and_blend_degradation():
    report = ConversionReport(Path("out.docx"))

    preflight_colors(_document(), report, target="docx")

    assert {issue.feature for issue in report.issues} == {"color-icc", "color-blend"}


def test_html_reports_icc_but_preserves_css_blend_mode():
    report = ConversionReport(Path("out.html"))

    preflight_colors(_document(), report, target="html")

    assert [issue.feature for issue in report.issues] == ["color-icc"]
