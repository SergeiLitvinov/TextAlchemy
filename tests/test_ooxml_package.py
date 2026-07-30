"""Tests for shared OOXML package graph helpers."""

from types import SimpleNamespace

from textalchemy.ooxml.package import EMU_PER_POINT, load_package_graph, package_part_for_relationship, points_to_emu


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
