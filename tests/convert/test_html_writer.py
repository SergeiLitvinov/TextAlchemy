"""Тесты DocumentModel → самодостаточный HTML."""

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
