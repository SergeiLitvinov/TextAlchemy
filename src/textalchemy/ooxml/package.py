"""Reusable helpers for importing and restoring OOXML package topology."""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import Any

from textalchemy.core.document_model import PackageGraph, PackagePart, PackageRelationship

DOCX_ROOT_PART = "/word/document.xml"
EMU_PER_POINT = 12700

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
    "endnotes": f"{_RELATIONSHIP_BASE}/endnotes",
    "footnotes": f"{_RELATIONSHIP_BASE}/footnotes",
    "numbering": f"{_RELATIONSHIP_BASE}/numbering",
    "styles": f"{_RELATIONSHIP_BASE}/styles",
    "theme": f"{_RELATIONSHIP_BASE}/theme",
}

RelationshipFilter = Callable[[Any], bool]


def points_to_emu(value: float) -> int:
    return round(value * EMU_PER_POINT)


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
            source.relate_to(
                destination,
                relationship.relationship_type,
                is_external=relationship.external,
            )
        else:
            source.rels.add_relationship(
                relationship.relationship_type,
                destination,
                relationship.id,
                is_external=relationship.external,
            )


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
