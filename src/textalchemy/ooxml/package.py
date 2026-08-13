"""Reusable helpers for importing and restoring OOXML package topology."""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import Any

from textalchemy.core.document_model import PackageGraph, PackagePart, PackageRelationship
from textalchemy.core.units import EMU_PER_POINT, points_to_emu

DOCX_ROOT_PART = "/word/document.xml"

OOXML_NAMESPACES = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}

_RELATIONSHIP_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
RELATIONSHIP_TYPE = {
    "comments": f"{_RELATIONSHIP_BASE}/comments",
    "comments_extended": "http://schemas.microsoft.com/office/2011/relationships/commentsExtended",
    "comments_extensible": "http://schemas.microsoft.com/office/2018/08/relationships/commentsExtensible",
    "people": "http://schemas.microsoft.com/office/2011/relationships/people",
    "diagram_data": f"{_RELATIONSHIP_BASE}/diagramData",
    "diagram_layout": f"{_RELATIONSHIP_BASE}/diagramLayout",
    "diagram_colors": f"{_RELATIONSHIP_BASE}/diagramColors",
    "diagram_quick_style": f"{_RELATIONSHIP_BASE}/diagramQuickStyle",
    "ole_object": f"{_RELATIONSHIP_BASE}/oleObject",
    "package": f"{_RELATIONSHIP_BASE}/package",
    "endnotes": f"{_RELATIONSHIP_BASE}/endnotes",
    "footnotes": f"{_RELATIONSHIP_BASE}/footnotes",
    "numbering": f"{_RELATIONSHIP_BASE}/numbering",
    "styles": f"{_RELATIONSHIP_BASE}/styles",
    "theme": f"{_RELATIONSHIP_BASE}/theme",
}

RelationshipFilter = Callable[[Any], bool]


def load_package_graph(
    root_part: Any,
    *,
    format_name: str,
    supported_relationships: Collection[str],
    recursive_relationships: Collection[str] = (),
    include: RelationshipFilter | None = None,
) -> PackageGraph | None:
    """Load selected root relationships and recursively preserve chosen targets."""

    graph = PackageGraph(format=format_name, root=str(root_part.partname))
    for relationship in root_part.rels.values():
        if relationship.reltype not in supported_relationships or relationship.is_external:
            continue
        if include is not None and not include(relationship):
            continue
        target_part = relationship.target_part
        target_name = _add_part(graph, target_part)
        graph.add_relationship(
            PackageRelationship(
                id=relationship.rId,
                relationship_type=relationship.reltype,
                source=graph.root,
                target=target_name,
            )
        )
        if relationship.reltype in recursive_relationships:
            _load_descendants(target_part, graph, set())
    return graph if graph.parts else None


def package_part_for_relationship(graph: PackageGraph | None, relationship_type: str) -> PackagePart | None:
    if graph is None:
        return None
    return graph.related_part(graph.root, relationship_type)


def restore_package_graph(root_part: Any, graph: PackageGraph) -> None:
    """Restore graph parts and relationships into a python-opc root part."""

    pack_uri_type, part_type = _opc_types(root_part)

    package = root_part.package
    parts = {
        name: part_type(pack_uri_type(part.name), part.media_type, part.data, package)
        for name, part in graph.parts.items()
    }
    root_relationship_types = {
        relationship.relationship_type
        for relationship in graph.relationships
        if relationship.source == graph.root
    }
    for relationship_id, relationship in list(root_part.rels.items()):
        if relationship.reltype in root_relationship_types:
            root_part.drop_rel(relationship_id)
    for relationship in graph.relationships:
        source = root_part if relationship.source == graph.root else parts[relationship.source]
        destination = relationship.target if relationship.external else parts[relationship.target]
        if source is root_part:
            _reserve_relationship_id(source, relationship.id)
            source.rels.add_relationship(
                relationship.relationship_type,
                destination,
                relationship.id,
                is_external=relationship.external,
            )
        else:
            source.rels.add_relationship(
                relationship.relationship_type,
                destination,
                relationship.id,
                is_external=relationship.external,
            )


def _reserve_relationship_id(root_part: Any, relationship_id: str) -> None:
    """Free an imported rId, moving a generated relationship without changing its references."""

    existing = root_part.rels.get(relationship_id)
    if existing is None:
        return
    replacement_id = root_part.rels._next_rId
    root_part.rels.add_relationship(
        existing.reltype,
        existing.target_ref if existing.is_external else existing.target_part,
        replacement_id,
        is_external=existing.is_external,
    )
    root_part.drop_rel(relationship_id)
    element = getattr(root_part, "element", None)
    if element is None:
        return
    for node in element.iter():
        for attribute, value in list(node.attrib.items()):
            if value == relationship_id:
                node.set(attribute, replacement_id)


def _load_descendants(part: Any, graph: PackageGraph, visited: set[str]) -> None:
    source_name = str(part.partname)
    if source_name in visited:
        return
    visited.add(source_name)
    for relationship in part.rels.values():
        target = relationship.target_ref
        if not relationship.is_external:
            target_part = relationship.target_part
            target = _add_part(graph, target_part)
        graph.add_relationship(
            PackageRelationship(
                id=relationship.rId,
                relationship_type=relationship.reltype,
                source=source_name,
                target=target,
                external=relationship.is_external,
            )
        )
        if not relationship.is_external:
            _load_descendants(relationship.target_part, graph, visited)


def _add_part(graph: PackageGraph, part: Any) -> str:
    name = str(part.partname)
    graph.add_part(PackagePart(name, part.content_type, part.blob))
    return name


def _opc_types(root_part: Any) -> tuple[type[Any], type[Any]]:
    if root_part.__class__.__module__.startswith("pptx."):
        from pptx.opc.packuri import PackURI
        from pptx.opc.part import Part
    else:
        from docx.opc.packuri import PackURI
        from docx.opc.part import Part
    return PackURI, Part


__all__ = [
    "DOCX_ROOT_PART",
    "EMU_PER_POINT",
    "OOXML_NAMESPACES",
    "RELATIONSHIP_TYPE",
    "load_package_graph",
    "package_part_for_relationship",
    "points_to_emu",
    "restore_package_graph",
]
