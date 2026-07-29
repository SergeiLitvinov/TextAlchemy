"""Тесты DocumentModel → DOCX и диагностического отчёта."""

import zipfile

from PIL import Image as PillowImage

from textalchemy.convert.docx_writer import write_docx_model
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
from textalchemy.formats.docx import read_docx_model


def _png_bytes(tmp_path):
    path = tmp_path / "source.png"
    PillowImage.new("RGB", (12, 8), "blue").save(path)
    return path.read_bytes()


def test_write_docx_model_roundtrip_preserves_core_content(tmp_path):
    output = tmp_path / "roundtrip.docx"
    document = DocumentModel(
        metadata={"title": "Round trip", "author": "TextAlchemy"},
        resources={"picture": Resource("picture", ResourceKind.RASTER_IMAGE, "image/png", data=_png_bytes(tmp_path))},
        sections=[
            Section(
                blocks=[
                    Paragraph(
                        content=[
                            TextRun(
                                "Linked text",
                                style=TextStyle(font_family="Arial", font_size=Length(13), bold=True, color="#336699"),
                                link="https://example.com",
                            ),
                            Image("picture", alt_text="blue image", box=Box(0, 0, 72, 48)),
                        ],
                        alignment="center",
                    ),
                    Table(
                        rows=[
                            TableRow(
                                cells=[
                                    TableCell(blocks=[Paragraph(content=[TextRun("wide")])], column_span=2),
                                    TableCell(blocks=[Paragraph(content=[TextRun("single")])]),
                                ]
                            )
                        ]
                    ),
                ],
                headers=[Paragraph(content=[TextRun("Header")])],
                footers=[Paragraph(content=[TextRun("Footer")])],
            )
        ],
    )

    report = write_docx_model(document, output)
    restored = read_docx_model(output)

    assert report.success is True
    assert report.lossless is True
    assert output.is_file()
    assert restored.metadata["title"] == "Round trip"
    assert restored.metadata["author"] == "TextAlchemy"
    assert restored.sections[0].headers[0].plain_text == "Header"
    assert restored.sections[0].footers[0].plain_text == "Footer"
    assert len(restored.resources) == 1
    assert report.metrics["images"] == 1
    assert report.metrics["tables"] == 1
    with zipfile.ZipFile(output) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        relationships = archive.read("word/_rels/document.xml.rels").decode("utf-8")
    assert "Linked text" in document_xml
    assert "https://example.com" in relationships


def test_write_docx_model_preserves_native_omml(tmp_path):
    output = tmp_path / "formula.docx"
    omml = '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:r><m:t>x+1</m:t></m:r></m:oMath>'
    document = DocumentModel(sections=[Section(blocks=[Formula(omml, FormulaFormat.OMML)])])

    report = write_docx_model(document, output)

    assert report.lossless is True
    with zipfile.ZipFile(output) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "<m:oMath" in xml
    assert "x+1" in xml


def test_write_docx_model_reports_formula_fallback(tmp_path):
    output = tmp_path / "latex.docx"
    document = DocumentModel(sections=[Section(blocks=[Formula("E=mc^2", FormulaFormat.LATEX, fallback_text="E = mc²")])])

    report = write_docx_model(document, output)

    assert report.success is True
    assert report.lossless is False
    assert any(issue.severity is IssueSeverity.LOSS and issue.feature == "formula" for issue in report.issues)
    restored = read_docx_model(output)
    assert restored.sections[0].blocks[0].plain_text == "E = mc²"


def test_write_docx_model_reports_missing_resource_as_error(tmp_path):
    output = tmp_path / "missing.docx"
    document = DocumentModel(sections=[Section(blocks=[Image("missing", alt_text="missing image")])])

    report = write_docx_model(document, output)

    assert report.success is False
    assert any(issue.severity is IssueSeverity.ERROR and issue.feature == "image" for issue in report.issues)
