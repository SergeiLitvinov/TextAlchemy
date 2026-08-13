"""Тесты сериализации и совместимых адаптеров модели документа."""

import json

import pytest

from textalchemy.core.color import ColorValue
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
    ImageProperties,
    Length,
    PackageGraph,
    PackagePart,
    PackageRelationship,
    Paragraph,
    ParagraphProperties,
    Provenance,
    ProvenanceEvent,
    Resource,
    ResourceKind,
    Section,
    SectionProperties,
    Table,
    TableCell,
    TableCellProperties,
    TableProperties,
    TableRow,
    TableRowProperties,
    TextRun,
    TextStyle,
    TextStyleProperties,
    VisualSurrogate,
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
        provenance=Provenance(
            source_format="docx",
            source_path="original.docx",
            package_part="/word/media/image1.svg",
            object_id="rId5",
            events=[ProvenanceEvent("import.docx", "copied vector resource")],
        ),
    )
    paragraph = Paragraph(
        content=[
            TextRun(
                "Result ",
                style=TextStyle(
                    font_family="PT Serif",
                    font_size=Length(12),
                    bold=True,
                    superscript=True,
                    color=ColorValue.from_cmyk(0.0, 1.0, 1.0, 0.0, alpha=0.8, icc_profile="press.icc"),
                ),
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
        provenance=Provenance(
            source_format="docx",
            package_part="/word/document.xml",
            object_id="paragraph-1",
            events=[ProvenanceEvent("normalize.runs", fallback_reason="unsupported WordArt")],
        ),
        visual_surrogate=VisualSurrogate(
            resource_id="vector-1",
            reason="WordArt editable approximation differs from source",
            media_type="image/svg+xml",
            fidelity=0.96,
        ),
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
        package=PackageGraph(
            format="ooxml",
            parts={
                "/word/theme/theme1.xml": PackagePart(
                    "/word/theme/theme1.xml",
                    "application/vnd.openxmlformats-officedocument.theme+xml",
                    b"<theme/>",
                )
            },
            relationships=[
                PackageRelationship(
                    "rIdTheme",
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
                    "/word/document.xml",
                    "/word/theme/theme1.xml",
                )
            ],
        ),
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
    assert payload["version"] == 2
    assert payload["document"]["property_schema_version"] == 1
    json.dumps(payload)


def test_unknown_version_is_rejected():
    payload = document_to_dict(_complex_document())
    payload["version"] = 99

    with pytest.raises(ValueError, match="unsupported document version"):
        document_from_dict(payload)


def test_version_one_document_is_migrated_to_typed_properties():
    payload = document_to_dict(_complex_document())
    payload["version"] = 1
    payload["document"].pop("property_schema_version")
    payload["document"]["sections"][0]["properties"] = {
        "start_type": "CONTINUOUS",
        "header_distance_pt": 24,
        "custom": "preserved",
    }
    payload["document"]["sections"][0]["blocks"][0]["content"][2]["properties"] = {
        "placement": "anchor",
        "behind_doc": 1,
    }

    restored = document_from_dict(payload)

    section_properties = restored.sections[0].properties
    image_properties = restored.sections[0].blocks[0].content[2].properties
    assert isinstance(section_properties, SectionProperties)
    assert section_properties.start_type == "CONTINUOUS"
    assert section_properties.header_distance_pt == 24.0
    assert section_properties["custom"] == "preserved"
    assert isinstance(image_properties, ImageProperties)
    assert image_properties.placement == "anchor"
    assert image_properties.behind_doc is True
    assert restored.version == 2


def test_legacy_ooxml_resources_are_migrated_to_package_graph():
    payload = document_to_dict(_complex_document())
    payload["version"] = 1
    payload["document"].pop("property_schema_version")
    payload["document"]["package"] = None
    payload["document"]["resources"]["docx-theme"] = {
        "id": "docx-theme",
        "kind": "attachment",
        "media_type": "application/vnd.openxmlformats-officedocument.theme+xml",
        "data_base64": "PHRoZW1lLz4=",
        "source": None,
        "filename": "theme1.xml",
        "properties": {
            "role": "docx-theme",
            "partname": "/word/theme/theme1.xml",
        },
    }

    restored = document_from_dict(payload)

    assert restored.package is not None
    assert restored.package.parts["/word/theme/theme1.xml"].data == b"<theme/>"
    assert "docx-theme" not in restored.resources


def test_unknown_property_schema_version_is_rejected():
    payload = document_to_dict(_complex_document())
    payload["document"]["property_schema_version"] = 99

    with pytest.raises(ValueError, match="unsupported property schema version"):
        document_from_dict(payload)


def test_structural_property_bags_keep_mapping_compatibility():
    paragraph = Paragraph(properties={"space_after_pt": 8, "extension": "kept"})
    style = TextStyle(properties={"style_type": "paragraph", "priority": 2})
    cell = TableCell(properties={"fill": "FF0000", "width_twips": 1200})
    row = TableRow(properties={"repeat_header": True})
    table = Table(properties={"autofit": False, "grid_widths_twips": [1200, 2400]})

    assert isinstance(paragraph.properties, ParagraphProperties)
    assert paragraph.properties.space_after_pt == 8.0
    assert paragraph.properties["extension"] == "kept"
    assert isinstance(style.properties, TextStyleProperties)
    assert style.properties.style_type == "paragraph"
    assert style.properties.priority == 2
    assert isinstance(cell.properties, TableCellProperties)
    assert cell.properties.width_twips == 1200
    assert isinstance(row.properties, TableRowProperties)
    assert row.properties.repeat_header is True
    assert isinstance(table.properties, TableProperties)
    assert table.properties.grid_widths_twips == [1200, 2400]


def test_package_graph_rejects_broken_internal_relationship():
    graph = PackageGraph(
        format="ooxml",
        relationships=[
            PackageRelationship("rId1", "urn:test", "/word/document.xml", "/word/missing.xml")
        ],
    )

    assert graph.validate() == ["unknown relationship target '/word/missing.xml'"]


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
