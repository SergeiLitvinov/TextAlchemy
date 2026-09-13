"""Наследование оформления текстовых заполнителей из макета и образца."""

from __future__ import annotations

from typing import Any

from textalchemy.formats.pptx_paragraph import frame_metadata, merge_paragraph_settings, merge_text_styles, paragraph_properties

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
MASTER_TYPES = {
    "ctrTitle": "title",
    "subTitle": "body",
    "obj": "body",
    "pic": "body",
    "chart": "body",
    "tbl": "body",
    "clipArt": "body",
    "dgm": "body",
    "media": "body",
}


def placeholder_chain(element: Any, layout: Any, master: Any) -> list[Any]:
    """Вернуть образец → макет для однозначной связи idx, затем типа."""
    ph = element.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
    if ph is None or layout is None:
        return []
    matches = [
        shape
        for shape in layout.iter(P + "sp")
        if (candidate := shape.find(f"{P}nvSpPr/{P}nvPr/{P}ph")) is not None and candidate.get("idx", "0") == ph.get("idx", "0")
    ]
    if len(matches) != 1:
        return []
    parent = matches[0]
    parent_ph = parent.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
    kind = parent_ph.get("type", "obj")
    kind = MASTER_TYPES.get(kind, kind)
    ancestors = (
        []
        if master is None
        else [
            shape
            for shape in master.iter(P + "sp")
            if (candidate := shape.find(f"{P}nvSpPr/{P}nvPr/{P}ph")) is not None and candidate.get("type", "obj") == kind
        ]
    )
    return (ancestors if len(ancestors) == 1 else []) + [parent]


def inherited_frame(chain: list[Any], element: Any) -> dict[str, Any]:
    # Materialize the DrawingML default before merging explicit master/layout settings.
    # Otherwise add_shape's default centered anchor changes an imported top-aligned box.
    result = {"anchor": "t"}
    for shape in [*chain, element]:
        result.update(frame_metadata(shape.find(P + "txBody")))
    return result


def inherited_paragraph(
    chain: list[Any],
    body: Any,
    level: int,
    meta: dict[str, Any],
    style: Any,
    *,
    parse_style: Any,
    alignments: dict[str, str],
    colors: dict[str, str],
) -> tuple[dict[str, Any], Any]:
    """Наложить свойства каждого уровня, сохранив независимость стилей фрагментов."""
    for shape in [*chain, None]:
        current = shape.find(P + "txBody") if shape is not None else body
        if current is None:
            continue
        nodes = [current.find(f"{A}lstStyle/{A}defPPr"), current.find(f"{A}lstStyle/{A}lvl{level + 1}pPr")]
        if shape is not None:
            matching = [
                paragraph.find(A + "pPr")
                for paragraph in current.findall(A + "p")
                if paragraph.find(A + "pPr") is not None and paragraph.find(A + "pPr").get("lvl", "0") == str(level)
            ]
            nodes.extend(matching[:1])
        for properties in nodes:
            if properties is None:
                continue
            meta = merge_paragraph_settings(meta, paragraph_properties(properties, alignments))
            style = merge_text_styles(style, parse_style(properties.find(A + "defRPr"), colors))
    return meta, style
