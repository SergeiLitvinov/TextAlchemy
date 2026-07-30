"""Тесты сериализации и совместимых адаптеров модели документа."""

import json

import pytest

from textalchemy.core.document_adapters import document_to_text, text_to_document
from textalchemy.core.document_codec import document_from_dict, document_from_json, document_to_dict, document_to_json
from textalchemy.core.document_model import (
    Box,
    ConversionMode,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    ImageCrop,
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
from textalchemy.core.types import Block, BlockType, DocFormat, Text
from textalchemy.core.types import Table as LegacyTable


def _complex_document() -> DocumentModel:
    resource = Resource(
        id="vector-1",
        kind=ResourceKind.VECTOR_IMAGE,
        media_type="image/svg+xml",
        data=b"<svg>\x00</svg>",
        filename="chart.svg",
    )
    paragraph = Paragraph(
        content=[
            TextRun(
                "Result ",
                style=TextStyle(font_family="PT Serif", font_size=Length(12), bold=True, superscript=True),
            ),
            Formula("x^2", FormulaFormat.LATEX, display=False),
            Image(
                "vector-1",
                alt_text="chart",
                box=Box(1, 2, 30, 40, rotation=5),
                crop=ImageCrop(left=0.1, top=0.2, right=0.05),
            ),
        ],
        style_id="body",
    )
    table = Table(rows=[TableRow(cells=[TableCell(blocks=[Paragraph(content=[TextRun("cell")])], column_span=2)])])
    return DocumentModel(
        sections=[
            Section(
                blocks=[paragraph, table],
                first_page_headers=[Paragraph(content=[TextRun("First {{ title }}")])],
                even_page_footers=[Paragraph(content=[TextRun("Even footer")])],
            )
        ],
        resources={resource.id: resource},
        styles={"body": TextStyle(language="ru-RU")},
        metadata={"title": "Тест"},
        mode=ConversionMode.FAITHFUL,
        source_format="docx",
    )


def test_json_roundtrip_preserves_structure_and_binary_resources():
    original = _complex_document()

    restored = document_from_json(document_to_json(original))

    assert restored == original
    assert restored.resources["vector-1"].data == b"<svg>\x00</svg>"


def test_serialized_document_has_explicit_format_and_version():
    payload = document_to_dict(_complex_document())

    assert payload["format"] == "textalchemy.document"
    assert payload["version"] == 1
    json.dumps(payload)


def test_unknown_version_is_rejected():
    payload = document_to_dict(_complex_document())
    payload["version"] = 99

    with pytest.raises(ValueError, match="unsupported document version"):
        document_from_dict(payload)


def test_broken_resource_reference_is_rejected_on_load():
    payload = document_to_dict(_complex_document())
    payload["document"]["resources"] = {}

    with pytest.raises(ValueError, match="unknown resource"):
        document_from_dict(payload)


def test_text_adapter_roundtrip_preserves_semantics_and_tables():
    source = Text(
        blocks=[Block(BlockType.HEADING, "Chapter", level=1), Block(BlockType.PARAGRAPH, "Body")],
        tables=[LegacyTable(rows=[["A", "B"], ["1", "2"]], page=2)],
        plain="Chapter\nBody\nA | B\n1 | 2",
        language="en",
        source_format=DocFormat.DOCX,
        engine="python-docx",
        warnings=["sample"],
        pages=2,
    )

    restored = document_to_text(text_to_document(source))

    assert [(block.type, block.text) for block in restored.blocks] == [
        (BlockType.HEADING, "Chapter"),
        (BlockType.PARAGRAPH, "Body"),
    ]
    assert restored.tables == source.tables
    assert restored.plain == source.plain
    assert restored.language == "en"
    assert restored.source_format is DocFormat.DOCX
    assert restored.warnings == ["sample"]
