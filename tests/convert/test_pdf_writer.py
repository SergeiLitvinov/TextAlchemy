"""Тесты DocumentModel → PDF."""

import pytest
from PIL import Image as PillowImage

from textalchemy.convert.pdf_writer import write_pdf_model
from textalchemy.core.diagnostics import IssueSeverity
from textalchemy.core.document_model import (
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
from textalchemy.fonts import FontResolver


def _png_bytes(tmp_path):
    path = tmp_path / "picture.png"
    PillowImage.new("RGB", (20, 12), "green").save(path)
    return path.read_bytes()


def test_write_pdf_model_preserves_page_text_table_image_link_and_metadata(tmp_path):
    import fitz

    output = tmp_path / "rich.pdf"
    document = DocumentModel(
        metadata={"title": "PDF report", "author": "TextAlchemy"},
        resources={"picture": Resource("picture", ResourceKind.RASTER_IMAGE, "image/png", data=_png_bytes(tmp_path))},
        sections=[
            Section(
                page=PageSettings(
                    width=Length(420),
                    height=Length(595),
                    margin_top=Length(50),
                    margin_right=Length(40),
                    margin_bottom=Length(50),
                    margin_left=Length(40),
                ),
                blocks=[
                    Paragraph(
                        content=[
                            TextRun(
                                "Отчёт PDF",
                                TextStyle(font_size=Length(18), bold=True, color="#174A7E"),
                                link="https://example.com/report",
                            )
                        ],
                        style_id="Heading1",
                    ),
                    Table(
                        rows=[
                            TableRow(
                                cells=[
                                    TableCell(blocks=[Paragraph(content=[TextRun("Параметр")])]),
                                    TableCell(blocks=[Paragraph(content=[TextRun("Значение")])]),
                                ]
                            )
                        ]
                    ),
                    Paragraph(content=[Image("picture", alt_text="Green diagram")]),
                ],
            )
        ],
    )

    report = write_pdf_model(document, output)

    assert report.success is True
    assert report.lossless is True
    assert report.metrics["pages"] == 1
    with fitz.open(output) as pdf:
        page = pdf[0]
        assert round(page.rect.width) == 420
        assert round(page.rect.height) == 595
        assert "Отчёт PDF" in page.get_text()
        assert "Параметр" in page.get_text()
        assert page.get_images()
        assert any(link.get("uri") == "https://example.com/report" for link in page.get_links())
        assert pdf.metadata["title"] == "PDF report"
        assert pdf.metadata["author"] == "TextAlchemy"


def test_write_pdf_model_repeats_header_and_footer_on_overflow_pages(tmp_path):
    import fitz

    output = tmp_path / "multipage.pdf"
    blocks = [Paragraph(content=[TextRun(f"Строка {index}: " + "длинный текст " * 14)]) for index in range(80)]
    document = DocumentModel(
        sections=[
            Section(
                blocks=blocks,
                headers=[Paragraph(content=[TextRun("Повторяемый заголовок")])],
                footers=[Paragraph(content=[TextRun("Повторяемый колонтитул")])],
            )
        ]
    )

    report = write_pdf_model(document, output)

    assert report.success is True
    assert report.metrics["pages"] > 1
    with fitz.open(output) as pdf:
        for page in pdf:
            text = page.get_text()
            assert "Повторяемый заголовок" in text
            assert "Повторяемый колонтитул" in text


def test_write_pdf_model_reports_formula_flattening(tmp_path):
    output = tmp_path / "formula.pdf"
    mathml = '<math xmlns="http://www.w3.org/1998/Math/MathML"><msup><mi>x</mi><mn>2</mn></msup></math>'
    document = DocumentModel(sections=[Section(blocks=[Formula(mathml, FormulaFormat.MATHML, fallback_text="x²")])])

    report = write_pdf_model(document, output)

    assert report.success is True
    assert report.lossless is False
    assert any(issue.severity is IssueSeverity.LOSS and issue.feature == "formula" for issue in report.issues)


def test_write_pdf_model_embeds_and_verifies_resolved_font(tmp_path):
    faces = [
        face
        for face in FontResolver.system().faces
        if face.embeddable and all(ord(character) in face.glyphs for character in "abc")
    ]
    if not faces:
        pytest.skip("no embeddable system font with basic Latin glyphs")
    face = faces[0]
    output = tmp_path / "embedded-font.pdf"
    document = DocumentModel(
        sections=[
            Section(blocks=[Paragraph(content=[TextRun("abc", TextStyle(font_family=face.family, font_size=Length(12)))])])
        ]
    )

    report = write_pdf_model(document, output)

    assert report.success is True
    assert report.metrics["font_embedding"]["embedded_faces"] >= 1
    assert report.metrics["font_embedding"]["verified_faces"] >= 1
