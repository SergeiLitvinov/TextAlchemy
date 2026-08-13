"""Tests for shared OOXML package graph helpers."""

from types import SimpleNamespace

from textalchemy.core.document_model import PackageGraph, PackagePart, PackageRelationship
from textalchemy.ooxml.package import (
    EMU_PER_POINT,
    RELATIONSHIP_TYPE,
    load_package_graph,
    package_part_for_relationship,
    points_to_emu,
    restore_package_graph,
)


def _part(name, media_type, data, relationships=()):
    return SimpleNamespace(
        partname=name,
        content_type=media_type,
        blob=data,
        rels={relationship.rId: relationship for relationship in relationships},
    )


def _internal(relationship_id, relationship_type, target_part):
    return SimpleNamespace(
        rId=relationship_id,
        reltype=relationship_type,
        is_external=False,
        target_part=target_part,
        target_ref=str(target_part.partname),
    )


def _external(relationship_id, relationship_type, target):
    return SimpleNamespace(
        rId=relationship_id,
        reltype=relationship_type,
        is_external=True,
        target_ref=target,
    )


def test_load_package_graph_preserves_recursive_and_external_relationships():
    hyperlink_type = "urn:test:hyperlink"
    image = _part("/word/media/note.png", "image/png", b"png")
    notes = _part(
        "/word/footnotes.xml",
        "application/xml",
        b"<notes/>",
        (
            _internal("rIdImage", "urn:test:image", image),
            _external("rIdLink", hyperlink_type, "https://example.com"),
        ),
    )
    footnote_type = "urn:test:footnotes"
    root = _part(
        "/word/document.xml",
        "application/xml",
        b"<document/>",
        (_internal("rIdNotes", footnote_type, notes),),
    )

    graph = load_package_graph(
        root,
        format_name="ooxml",
        supported_relationships={footnote_type},
        recursive_relationships={footnote_type},
    )

    assert graph is not None
    assert set(graph.parts) == {"/word/footnotes.xml", "/word/media/note.png"}
    assert package_part_for_relationship(graph, footnote_type) == graph.parts["/word/footnotes.xml"]
    external = next(item for item in graph.relationships if item.relationship_type == hyperlink_type)
    assert external.external is True
    assert external.target == "https://example.com"
    assert graph.validate() == []


def test_point_to_emu_conversion_uses_shared_ooxml_unit():
    assert EMU_PER_POINT == 12700
    assert points_to_emu(72) == 914400


def test_load_package_graph_keeps_comments_smartart_and_ole_payloads():
    comments = _part("/word/comments.xml", "application/xml", b"<comments/>")
    diagram_layout = _part("/word/diagrams/layout1.xml", "application/xml", b"<layout/>")
    diagram_data = _part(
        "/word/diagrams/data1.xml",
        "application/xml",
        b"<data/>",
        (_internal("rIdLayout", RELATIONSHIP_TYPE["diagram_layout"], diagram_layout),),
    )
    embedded = _part("/word/embeddings/workbook.xlsx", "application/octet-stream", b"xlsx")
    root = _part(
        "/word/document.xml",
        "application/xml",
        b"<document/>",
        (
            _internal("rIdComments", RELATIONSHIP_TYPE["comments"], comments),
            _internal("rIdDiagram", RELATIONSHIP_TYPE["diagram_data"], diagram_data),
            _internal("rIdOle", RELATIONSHIP_TYPE["package"], embedded),
        ),
    )

    graph = load_package_graph(
        root,
        format_name="ooxml",
        supported_relationships=set(RELATIONSHIP_TYPE.values()),
        recursive_relationships={
            RELATIONSHIP_TYPE["comments"],
            RELATIONSHIP_TYPE["diagram_data"],
            RELATIONSHIP_TYPE["package"],
        },
    )

    assert graph is not None
    assert set(graph.parts) == {
        "/word/comments.xml",
        "/word/diagrams/data1.xml",
        "/word/diagrams/layout1.xml",
        "/word/embeddings/workbook.xlsx",
    }
    assert {relationship.relationship_type for relationship in graph.relationships} >= {
        RELATIONSHIP_TYPE["comments"],
        RELATIONSHIP_TYPE["diagram_data"],
        RELATIONSHIP_TYPE["diagram_layout"],
        RELATIONSHIP_TYPE["package"],
    }
    assert graph.validate() == []


def test_restore_package_graph_preserves_imported_id_and_rewrites_collision():
    from docx import Document
    from docx.opc.constants import RELATIONSHIP_TYPE as DOCX_RELATIONSHIP_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    target = Document()
    paragraph = target.add_paragraph()
    hyperlink_id = target.part.relate_to(
        "https://example.com",
        DOCX_RELATIONSHIP_TYPE.HYPERLINK,
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), hyperlink_id)
    paragraph._p.append(hyperlink)
    graph = PackageGraph(format="ooxml", root="/word/document.xml")
    graph.add_part(PackagePart("/word/comments.xml", "application/xml", b"<w:comments xmlns:w='x'/>") )
    graph.add_relationship(
        PackageRelationship(
            id=hyperlink_id,
            relationship_type=RELATIONSHIP_TYPE["comments"],
            source=graph.root,
            target="/word/comments.xml",
        )
    )

    restore_package_graph(target.part, graph)

    assert target.part.rels[hyperlink_id].reltype == RELATIONSHIP_TYPE["comments"]
    moved = next(rel for rel in target.part.rels.values() if rel.reltype == DOCX_RELATIONSHIP_TYPE.HYPERLINK)
    assert moved.rId != hyperlink_id
    assert hyperlink.get(qn("r:id")) == moved.rId
