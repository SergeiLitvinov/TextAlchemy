"""Версионированная JSON-сериализация :class:`DocumentModel`."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from textalchemy.core.document_model import (
    Block,
    Box,
    ConversionMode,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    ImageCrop,
    Length,
    PackageGraph,
    PackagePart,
    PackageRelationship,
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
from textalchemy.core.properties import PROPERTY_SCHEMA_VERSION, VersionedProperties

FORMAT_NAME = "textalchemy.document"
FORMAT_VERSION = 2
SUPPORTED_FORMAT_VERSIONS = frozenset({1, FORMAT_VERSION})


def document_to_dict(document: DocumentModel) -> dict[str, Any]:
    """Преобразовать модель в JSON-совместимый словарь без потери ресурсов."""

    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "document": {
            "property_schema_version": PROPERTY_SCHEMA_VERSION,
            "mode": document.mode.value,
            "source_format": document.source_format,
            "metadata": document.metadata,
            "package": _package_to_dict(document.package),
            "styles": {key: _style_to_dict(value) for key, value in document.styles.items()},
            "resources": {key: _resource_to_dict(value) for key, value in document.resources.items()},
            "sections": [_section_to_dict(section) for section in document.sections],
        },
    }


def document_from_dict(payload: dict[str, Any]) -> DocumentModel:
    """Восстановить модель и отклонить неизвестный формат или версию."""

    if payload.get("format") != FORMAT_NAME:
        raise ValueError(f"unsupported document format: {payload.get('format')!r}")
    version = payload.get("version")
    if version not in SUPPORTED_FORMAT_VERSIONS:
        raise ValueError(f"unsupported document version: {version!r}")
    raw = payload.get("document")
    if not isinstance(raw, dict):
        raise ValueError("document payload must be an object")
    property_schema_version = raw.get("property_schema_version", 1)
    if property_schema_version != PROPERTY_SCHEMA_VERSION:
        raise ValueError(f"unsupported property schema version: {property_schema_version!r}")

    document = DocumentModel(
        sections=[_section_from_dict(value) for value in raw.get("sections", [])],
        resources={key: _resource_from_dict(value) for key, value in raw.get("resources", {}).items()},
        styles={key: _style_from_dict(value) for key, value in raw.get("styles", {}).items()},
        metadata=dict(raw.get("metadata", {})),
        package=_package_from_dict(raw.get("package")),
        mode=ConversionMode(raw.get("mode", ConversionMode.BALANCED.value)),
        source_format=raw.get("source_format"),
        version=FORMAT_VERSION,
    )
    _migrate_legacy_package_resources(document)
    errors = document.validate()
    if errors:
        raise ValueError("invalid document model: " + "; ".join(errors))
    return document


def document_to_json(document: DocumentModel, *, indent: int | None = None) -> str:
    return json.dumps(document_to_dict(document), ensure_ascii=False, indent=indent)


def document_from_json(value: str | bytes) -> DocumentModel:
    return document_from_dict(json.loads(value))


def save_document(document: DocumentModel, path: str | Path, *, indent: int | None = 2) -> Path:
    from textalchemy.core.io import atomic_write_text

    output = Path(path)
    atomic_write_text(output, document_to_json(document, indent=indent), encoding="utf-8")
    return output


def load_document(path: str | Path) -> DocumentModel:
    return document_from_json(Path(path).read_text(encoding="utf-8"))


def _length_to_value(value: Length | None) -> float | None:
    return value.pt if value is not None else None


def _length_from_value(value: float | None) -> Length | None:
    return Length(float(value)) if value is not None else None


def _box_to_dict(value: Box | None) -> dict[str, float] | None:
    if value is None:
        return None
    return {"x": value.x, "y": value.y, "width": value.width, "height": value.height, "rotation": value.rotation}


def _box_from_dict(value: dict[str, Any] | None) -> Box | None:
    return Box(**value) if value is not None else None


def _crop_to_dict(value: ImageCrop | None) -> dict[str, float] | None:
    if value is None:
        return None
    return {"left": value.left, "top": value.top, "right": value.right, "bottom": value.bottom}


def _crop_from_dict(value: dict[str, Any] | None) -> ImageCrop | None:
    return ImageCrop(**value) if value is not None else None


def _properties_to_dict(value: dict[str, Any] | VersionedProperties) -> dict[str, Any]:
    return value.to_dict() if isinstance(value, VersionedProperties) else dict(value)


def _package_to_dict(value: PackageGraph | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "format": value.format,
        "root": value.root,
        "parts": {
            name: {
                "name": part.name,
                "media_type": part.media_type,
                "data_base64": base64.b64encode(part.data).decode("ascii"),
            }
            for name, part in value.parts.items()
        },
        "relationships": [
            {
                "id": relationship.id,
                "relationship_type": relationship.relationship_type,
                "source": relationship.source,
                "target": relationship.target,
                "external": relationship.external,
            }
            for relationship in value.relationships
        ],
    }


def _package_from_dict(value: dict[str, Any] | None) -> PackageGraph | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("package payload must be an object")
    parts: dict[str, PackagePart] = {}
    for name, raw_part in value.get("parts", {}).items():
        try:
            data = base64.b64decode(raw_part["data_base64"], validate=True)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid package part {name!r}") from error
        part = PackagePart(
            name=raw_part.get("name", name),
            media_type=raw_part["media_type"],
            data=data,
        )
        parts[name] = part
    return PackageGraph(
        format=str(value.get("format", "")),
        root=str(value.get("root", "/word/document.xml")),
        parts=parts,
        relationships=[
            PackageRelationship(
                id=item["id"],
                relationship_type=item["relationship_type"],
                source=item["source"],
                target=item["target"],
                external=bool(item.get("external", False)),
            )
            for item in value.get("relationships", [])
        ],
    )


def _migrate_legacy_package_resources(document: DocumentModel) -> None:
    if document.package is not None:
        return
    definitions = {
        "docx-footnotes": (
            "/word/footnotes.xml",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes",
        ),
        "docx-endnotes": (
            "/word/endnotes.xml",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes",
        ),
        "docx-numbering": (
            "/word/numbering.xml",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering",
        ),
        "docx-styles": (
            "/word/styles.xml",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
        ),
        "docx-theme": (
            "/word/theme/theme1.xml",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
        ),
    }
    graph = PackageGraph(format="ooxml")
    migrated: set[str] = set()
    for resource_id, resource in list(document.resources.items()):
        role = str(resource.properties.get("role") or resource_id)
        definition = definitions.get(role)
        if definition is None or resource.data is None:
            continue
        default_name, relationship_type = definition
        part_name = str(resource.properties.get("partname") or default_name)
        graph.add_part(PackagePart(part_name, resource.media_type, resource.data))
        graph.add_relationship(
            PackageRelationship(
                id=f"rIdMigrated{len(graph.relationships) + 1}",
                relationship_type=relationship_type,
                source="/word/document.xml",
                target=part_name,
            )
        )
        migrated.add(resource_id)
        for raw_relationship in resource.properties.get("relationships", []):
            related_resource_id = raw_relationship.get("resource_id")
            if raw_relationship.get("external"):
                target = str(raw_relationship.get("target", ""))
            elif related_resource_id in document.resources:
                related = document.resources[related_resource_id]
                if related.data is None:
                    continue
                target = str(related.properties.get("partname") or f"/word/media/{related.filename or related_resource_id}")
                graph.add_part(PackagePart(target, related.media_type, related.data))
                migrated.add(str(related_resource_id))
            else:
                continue
            graph.add_relationship(
                PackageRelationship(
                    id=str(raw_relationship["id"]),
                    relationship_type=str(raw_relationship["type"]),
                    source=part_name,
                    target=target,
                    external=bool(raw_relationship.get("external", False)),
                )
            )
    if not graph.parts:
        return
    document.package = graph
    for resource_id in migrated:
        document.resources.pop(resource_id, None)


def _style_to_dict(value: TextStyle) -> dict[str, Any]:
    return {
        "font_family": value.font_family,
        "font_size_pt": _length_to_value(value.font_size),
        "bold": value.bold,
        "italic": value.italic,
        "underline": value.underline,
        "superscript": value.superscript,
        "subscript": value.subscript,
        "color": value.color,
        "background": value.background,
        "language": value.language,
        "properties": _properties_to_dict(value.properties),
    }


def _style_from_dict(value: dict[str, Any]) -> TextStyle:
    return TextStyle(
        font_family=value.get("font_family"),
        font_size=_length_from_value(value.get("font_size_pt")),
        bold=value.get("bold"),
        italic=value.get("italic"),
        underline=value.get("underline"),
        superscript=value.get("superscript"),
        subscript=value.get("subscript"),
        color=value.get("color"),
        background=value.get("background"),
        language=value.get("language"),
        properties=dict(value.get("properties", {})),
    )


def _resource_to_dict(value: Resource) -> dict[str, Any]:
    return {
        "id": value.id,
        "kind": value.kind.value,
        "media_type": value.media_type,
        "data_base64": base64.b64encode(value.data).decode("ascii") if value.data is not None else None,
        "source": value.source,
        "filename": value.filename,
        "properties": value.properties,
    }


def _resource_from_dict(value: dict[str, Any]) -> Resource:
    encoded = value.get("data_base64")
    try:
        data = base64.b64decode(encoded, validate=True) if encoded is not None else None
    except (ValueError, TypeError) as error:
        raise ValueError(f"invalid base64 resource {value.get('id')!r}") from error
    return Resource(
        id=value["id"],
        kind=ResourceKind(value["kind"]),
        media_type=value["media_type"],
        data=data,
        source=value.get("source"),
        filename=value.get("filename"),
        properties=dict(value.get("properties", {})),
    )


def _inline_to_dict(value: TextRun | Formula | Image) -> dict[str, Any]:
    if isinstance(value, TextRun):
        return {
            "type": "text",
            "text": value.text,
            "style": _style_to_dict(value.style),
            "link": value.link,
            "properties": _properties_to_dict(value.properties),
        }
    return _block_to_dict(value)


def _inline_from_dict(value: dict[str, Any]) -> TextRun | Formula | Image:
    if value.get("type") == "text":
        return TextRun(
            text=value.get("text", ""),
            style=_style_from_dict(value.get("style", {})),
            link=value.get("link"),
            properties=dict(value.get("properties", {})),
        )
    block = _block_from_dict(value)
    if not isinstance(block, (Formula, Image)):
        raise ValueError(f"invalid inline element: {value.get('type')!r}")
    return block


def _block_to_dict(value: Block) -> dict[str, Any]:
    if isinstance(value, Paragraph):
        return {
            "type": "paragraph",
            "content": [_inline_to_dict(item) for item in value.content],
            "style_id": value.style_id,
            "alignment": value.alignment,
            "box": _box_to_dict(value.box),
            "properties": _properties_to_dict(value.properties),
        }
    if isinstance(value, Table):
        return {
            "type": "table",
            "rows": [
                {
                    "cells": [
                        {
                            "blocks": [_block_to_dict(block) for block in cell.blocks],
                            "row_span": cell.row_span,
                            "column_span": cell.column_span,
                            "properties": _properties_to_dict(cell.properties),
                        }
                        for cell in row.cells
                    ],
                    "properties": _properties_to_dict(row.properties),
                }
                for row in value.rows
            ],
            "style_id": value.style_id,
            "box": _box_to_dict(value.box),
            "properties": _properties_to_dict(value.properties),
        }
    if isinstance(value, Formula):
        return {
            "type": "formula",
            "value": value.value,
            "format": value.format.value,
            "display": value.display,
            "fallback_text": value.fallback_text,
            "box": _box_to_dict(value.box),
            "properties": value.properties,
        }
    if isinstance(value, Image):
        return {
            "type": "image",
            "resource_id": value.resource_id,
            "alt_text": value.alt_text,
            "box": _box_to_dict(value.box),
            "properties": _properties_to_dict(value.properties),
            "crop": _crop_to_dict(value.crop),
        }
    raise TypeError(f"unsupported block: {type(value).__name__}")


def _block_from_dict(value: dict[str, Any]) -> Block:
    element_type = value.get("type")
    if element_type == "paragraph":
        return Paragraph(
            content=[_inline_from_dict(item) for item in value.get("content", [])],
            style_id=value.get("style_id"),
            alignment=value.get("alignment"),
            box=_box_from_dict(value.get("box")),
            properties=dict(value.get("properties", {})),
        )
    if element_type == "table":
        rows = []
        for raw_row in value.get("rows", []):
            cells = [
                TableCell(
                    blocks=[_block_from_dict(block) for block in raw_cell.get("blocks", [])],
                    row_span=raw_cell.get("row_span", 1),
                    column_span=raw_cell.get("column_span", 1),
                    properties=dict(raw_cell.get("properties", {})),
                )
                for raw_cell in raw_row.get("cells", [])
            ]
            rows.append(TableRow(cells=cells, properties=dict(raw_row.get("properties", {}))))
        return Table(
            rows=rows,
            style_id=value.get("style_id"),
            box=_box_from_dict(value.get("box")),
            properties=dict(value.get("properties", {})),
        )
    if element_type == "formula":
        return Formula(
            value=value.get("value", ""),
            format=FormulaFormat(value["format"]),
            display=value.get("display", False),
            fallback_text=value.get("fallback_text", ""),
            box=_box_from_dict(value.get("box")),
            properties=dict(value.get("properties", {})),
        )
    if element_type == "image":
        return Image(
            resource_id=value["resource_id"],
            alt_text=value.get("alt_text", ""),
            box=_box_from_dict(value.get("box")),
            properties=dict(value.get("properties", {})),
            crop=_crop_from_dict(value.get("crop")),
        )
    raise ValueError(f"unsupported element type: {element_type!r}")


def _page_to_dict(value: PageSettings) -> dict[str, float]:
    return {
        "width_pt": value.width.pt,
        "height_pt": value.height.pt,
        "margin_top_pt": value.margin_top.pt,
        "margin_right_pt": value.margin_right.pt,
        "margin_bottom_pt": value.margin_bottom.pt,
        "margin_left_pt": value.margin_left.pt,
    }


def _page_from_dict(value: dict[str, Any]) -> PageSettings:
    defaults = PageSettings()
    return PageSettings(
        width=Length(value.get("width_pt", defaults.width.pt)),
        height=Length(value.get("height_pt", defaults.height.pt)),
        margin_top=Length(value.get("margin_top_pt", defaults.margin_top.pt)),
        margin_right=Length(value.get("margin_right_pt", defaults.margin_right.pt)),
        margin_bottom=Length(value.get("margin_bottom_pt", defaults.margin_bottom.pt)),
        margin_left=Length(value.get("margin_left_pt", defaults.margin_left.pt)),
    )


def _section_to_dict(value: Section) -> dict[str, Any]:
    return {
        "blocks": [_block_to_dict(block) for block in value.blocks],
        "page": _page_to_dict(value.page),
        "headers": [_block_to_dict(block) for block in value.headers],
        "footers": [_block_to_dict(block) for block in value.footers],
        "first_page_headers": [_block_to_dict(block) for block in value.first_page_headers],
        "first_page_footers": [_block_to_dict(block) for block in value.first_page_footers],
        "even_page_headers": [_block_to_dict(block) for block in value.even_page_headers],
        "even_page_footers": [_block_to_dict(block) for block in value.even_page_footers],
        "properties": _properties_to_dict(value.properties),
    }


def _section_from_dict(value: dict[str, Any]) -> Section:
    return Section(
        blocks=[_block_from_dict(block) for block in value.get("blocks", [])],
        page=_page_from_dict(value.get("page", {})),
        headers=[_block_from_dict(block) for block in value.get("headers", [])],
        footers=[_block_from_dict(block) for block in value.get("footers", [])],
        first_page_headers=[_block_from_dict(block) for block in value.get("first_page_headers", [])],
        first_page_footers=[_block_from_dict(block) for block in value.get("first_page_footers", [])],
        even_page_headers=[_block_from_dict(block) for block in value.get("even_page_headers", [])],
        even_page_footers=[_block_from_dict(block) for block in value.get("even_page_footers", [])],
        properties=dict(value.get("properties", {})),
    )


__all__ = [
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "document_from_dict",
    "document_from_json",
    "document_to_dict",
    "document_to_json",
    "load_document",
    "save_document",
]
