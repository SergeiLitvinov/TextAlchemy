"""Inventory advanced DOCX features and their preservation level."""

from __future__ import annotations

from collections import Counter
from typing import Any

_FEATURE_TAGS = {
    "tracked_insertions": {"ins", "moveTo"},
    "tracked_deletions": {"del", "moveFrom"},
    "comments": {"commentReference", "commentRangeStart", "commentRangeEnd"},
    "content_controls": {"sdt"},
    "text_boxes": {"txbxContent", "textbox"},
    "wordart": {"textOutline", "textFill", "textPath"},
    "protected_fields": {"documentProtection"},
}


def inspect_docx_features(document: Any) -> dict[str, Any]:
    """Return machine-readable counts and preservation claims for advanced OOXML."""
    from lxml import etree

    counts: Counter[str] = Counter()
    roots = [document.part.element]
    for relationship in document.part.rels.values():
        if relationship.is_external or not hasattr(relationship.target_part, "blob"):
            continue
        media_type = str(getattr(relationship.target_part, "content_type", ""))
        if "xml" not in media_type:
            continue
        try:
            roots.append(etree.fromstring(relationship.target_part.blob))
        except etree.XMLSyntaxError:
            continue
    protection_xml: str | None = None
    for root in roots:
        for element in root.iter():
            local = etree.QName(element).localname
            if local == "documentProtection" and protection_xml is None:
                protection_xml = etree.tostring(element, encoding="unicode")
            for feature, tags in _FEATURE_TAGS.items():
                if local in tags:
                    counts[feature] += 1

    relationship_counts: Counter[str] = Counter()
    part_names: dict[str, list[str]] = {}
    for relationship in document.part.rels.values():
        feature = _relationship_feature(relationship.reltype)
        if feature is None:
            continue
        relationship_counts[feature] += 1
        if not relationship.is_external:
            part_names.setdefault(feature, []).append(str(relationship.target_part.partname))
    counts.update(relationship_counts)

    native = {
        "comments",
        "content_controls",
        "embedded_ole",
        "smartart",
        "text_boxes",
        "tracked_deletions",
        "tracked_insertions",
        "wordart",
    }
    result: dict[str, Any] = {
        "schema_version": 1,
        "features": {
            feature: {
                "count": count,
                "preservation": "native-ooxml" if feature in native else "diagnostic-only",
                "package_parts": sorted(part_names.get(feature, [])),
            }
            for feature, count in sorted(counts.items())
            if count
        },
    }
    if protection_xml is not None:
        result["document_protection_xml"] = protection_xml
    return result


def _relationship_feature(relationship_type: str) -> str | None:
    suffix = relationship_type.rsplit("/", 1)[-1].casefold()
    if suffix.startswith("comment") or suffix == "people":
        return "comments"
    if suffix in {"diagramdata", "diagramlayout", "diagramcolors", "diagramquickstyle"}:
        return "smartart"
    if suffix in {"oleobject", "package"}:
        return "embedded_ole"
    return None


__all__ = ["inspect_docx_features"]
