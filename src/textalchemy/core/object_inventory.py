"""Recursive inventory of model objects, independent of run segmentation."""

import hashlib
from typing import Any, Iterator

from textalchemy.core.document_model import Formula, Image, Paragraph, Resource, Table, TextRun
from textalchemy.core.text_flow import TextFlowFingerprint

OBJECT_INVENTORY_SCOPE = "model-recursive-objects-v1"


def inspect_objects(
    value: Any, location: str, page_index: int, resources: dict[str, Resource], *, parent: str | None = None,
    text_flow: TextFlowFingerprint | None = None,
) -> Iterator[dict[str, Any]]:
    provenance = getattr(value, "provenance", None)
    provenance_data = None
    if provenance is not None:
        identity = "|".join(str(item or "") for item in (
            provenance.source_format, provenance.source_path, provenance.page, provenance.package_part, provenance.object_id,
        )) if provenance.object_id is not None else None
        provenance_data = {
            "identity": identity, "source_format": provenance.source_format, "source_path": provenance.source_path,
            "page": provenance.page, "object_id": provenance.object_id, "package_part": provenance.package_part,
        }
    box = getattr(value, "box", None)
    geometry = None if box is None else {
        "x": round(box.x, 3), "y": round(box.y, 3), "width": round(box.width, 3),
        "height": round(box.height, 3), "rotation": round(box.rotation, 3),
    }
    content = _object_content(value, resources)
    # Runs may split/merge during serialization without changing the paragraph.
    text = "".join(item.text for item in value.content if isinstance(item, TextRun)) if isinstance(value, Paragraph) else None
    # Formula values may be LaTeX/OMML source, not comparable visible text.
    if text is not None and text_flow is not None:
        text_flow.add(text)
    yield {
        "location": location, "parent_location": parent, "page": page_index, "type": type(value).__name__.lower(),
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest() if content else None,
        "geometry": geometry, "style_id": getattr(value, "style_id", None), "provenance": provenance_data,
        "text_characters": len(text) if text is not None else None,
        "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None,
    }
    if isinstance(value, Table):
        for row_index, row in enumerate(value.rows):
            for cell_index, cell in enumerate(row.cells):
                for block_index, block in enumerate(cell.blocks):
                    child = f"{location}.rows[{row_index}].cells[{cell_index}].blocks[{block_index}]"
                    yield from inspect_objects(block, child, page_index, resources, parent=location, text_flow=text_flow)
    elif isinstance(value, Paragraph):
        for inline_index, inline in enumerate(value.content):
            if isinstance(inline, (Image, Formula)):
                yield from inspect_objects(
                    inline, f"{location}.content[{inline_index}]", page_index, resources, parent=location, text_flow=text_flow,
                )


def _object_content(value: Any, resources: dict[str, Resource]) -> str:
    if isinstance(value, Paragraph):
        return value.plain_text
    if isinstance(value, Formula):
        return value.value
    if isinstance(value, Image):
        resource = resources.get(value.resource_id)
        return hashlib.sha256(resource.data).hexdigest() if resource is not None and resource.data else ""
    if isinstance(value, Table):
        return "\n".join(
            "\t".join(" ".join(_object_content(block, resources) for block in cell.blocks) for cell in row.cells)
            for row in value.rows
        )
    return ""
