"""Тесты богатой промежуточной модели документа."""

import pytest

from textalchemy.core.document_model import (
    ConversionMode,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
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


def test_paragraph_plain_text_preserves_formula_and_image_fallbacks():
    paragraph = Paragraph(content=[
        TextRun("Energy: ", style=TextStyle(bold=True)),
        Formula("E=mc^2", FormulaFormat.LATEX, fallback_text="E = mc²"),
        Image("diagram", alt_text=" [diagram]"),
    ])

    assert paragraph.plain_text == "Energy: E = mc² [diagram]"


def test_document_accepts_raster_and_vector_resources():
    document = DocumentModel(mode=ConversionMode.FAITHFUL)
    document.add_resource(Resource("photo", ResourceKind.RASTER_IMAGE, "image/png", data=b"png"))
    document.add_resource(Resource("chart", ResourceKind.VECTOR_IMAGE, "image/svg+xml", data=b"<svg/>"))

    assert document.resources["photo"].kind is ResourceKind.RASTER_IMAGE
    assert document.resources["chart"].kind is ResourceKind.VECTOR_IMAGE
    assert document.validate() == []


def test_resource_requires_content_or_source():
    with pytest.raises(ValueError, match="data or source"):
        Resource("missing", ResourceKind.RASTER_IMAGE, "image/png")


def test_duplicate_resource_is_rejected():
    document = DocumentModel()
    resource = Resource("same", ResourceKind.RASTER_IMAGE, "image/png", data=b"x")
    document.add_resource(resource)

    with pytest.raises(ValueError, match="duplicate resource"):
        document.add_resource(resource)


def test_validate_reports_nested_missing_resource():
    table = Table(rows=[TableRow(cells=[TableCell(blocks=[Paragraph(content=[Image("missing")])])])])
    document = DocumentModel(sections=[Section(blocks=[table])])

    errors = document.validate()

    assert len(errors) == 1
    assert "unknown resource 'missing'" in errors[0]
    assert "rows[0].cells[0]" in errors[0]
