"""DOCX drawing importer for raster/vector resources and anchor geometry."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from textalchemy.core.document_model import (
    VECTOR_IMAGE_MEDIA_TYPES,
    Box,
    DocumentModel,
    Image,
    ImageCrop,
    Resource,
    ResourceKind,
    attach_visual_surrogate,
)
from textalchemy.core.units import emu_to_points, ooxml_angle_to_degrees
from textalchemy.formats.svg_color import parse_svg_color, svg_color_catalog
from textalchemy.ooxml.color import resolve_drawingml_color


def read_run_images(run: Any, model: DocumentModel) -> list[Image]:
    from docx.oxml.ns import qn
    from lxml import etree

    images: list[Image] = []
    for blip in run._r.xpath(".//a:blip"):
        relationship_id = blip.get(qn("r:embed"))
        fallback_part = run.part.related_parts.get(relationship_id) if relationship_id else None
        image_part = _preferred_svg_part(blip, run) or fallback_part
        if image_part is None or not hasattr(image_part, "blob"):
            continue
        resource_id = _add_image_resource(image_part, model)
        drawing = next(
            (
                ancestor
                for ancestor in blip.iterancestors()
                if etree.QName(ancestor).localname in {"inline", "anchor"}
            ),
            None,
        )
        extent = drawing.xpath("./wp:extent") if drawing is not None else []
        box = None
        if extent:
            x, y = _drawing_position(drawing)
            box = Box(
                x,
                y,
                emu_to_points(float(extent[0].get("cx", 0))),
                emu_to_points(float(extent[0].get("cy", 0))),
            )
        doc_properties = drawing.xpath("./wp:docPr") if drawing is not None else []
        alt_text = ""
        properties = _drawing_properties(drawing)
        properties.update(_drawing_effects(blip, model))
        if fallback_part is not None and fallback_part is not image_part and hasattr(fallback_part, "blob"):
            properties["fallback_resource_id"] = _add_image_resource(fallback_part, model)
        crop = _drawing_crop(blip)
        rotation = _drawing_rotation(blip)
        if box is not None:
            box.rotation = rotation
        if doc_properties:
            alt_text = doc_properties[0].get("descr") or doc_properties[0].get("title") or ""
            properties["name"] = doc_properties[0].get("name")
        fallback_id = properties.get("fallback_resource_id")
        image = Image(resource_id=resource_id, alt_text=alt_text, box=box, properties=properties, crop=crop)
        if fallback_id:
            attach_visual_surrogate(
                image,
                model.resources[fallback_id],
                reason="Office stores a raster preview beside the editable SVG resource",
            )
        images.append(image)
    return images


def read_run_vml_colors(run: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Catalog explicit VML paints while retaining source XML for later rendering."""
    from lxml import etree

    colors: list[dict[str, Any]] = []
    xml: list[str] = []
    for shape in run._r.xpath(".//*[local-name()='shape' or local-name()='rect' or local-name()='oval']"):
        xml.append(etree.tostring(shape, encoding="unicode"))
        for attribute, role in (("fillcolor", "fill"), ("strokecolor", "stroke")):
            raw = shape.get(attribute)
            color = parse_svg_color(raw) if raw else None
            if color is not None:
                colors.append({"element": etree.QName(shape).localname, "role": role, "color": color.to_dict()})
        for child in shape:
            local_name = etree.QName(child).localname
            if local_name not in {"fill", "stroke"}:
                continue
            raw = child.get("color")
            opacity = _vml_opacity(child.get("opacity"))
            color = parse_svg_color(raw, opacity=opacity) if raw else None
            if color is not None:
                colors.append({"element": local_name, "role": local_name, "color": color.to_dict()})
    return colors, xml


def _vml_opacity(value: str | None) -> float | None:
    if value is None:
        return None
    token = value.strip()
    try:
        if token.endswith("%"):
            return float(token[:-1]) / 100.0
        if token.lower().endswith("f"):
            return int(token[:-1]) / 65536.0
        return float(token)
    except ValueError:
        return None


def _preferred_svg_part(blip: Any, run: Any) -> Any | None:
    from docx.oxml.ns import qn

    for svg_blip in blip.xpath(".//*[local-name()='svgBlip']"):
        relationship_id = svg_blip.get(qn("r:embed"))
        part = run.part.related_parts.get(relationship_id) if relationship_id else None
        if part is not None and getattr(part, "content_type", None) == "image/svg+xml":
            return part
    return None


def _add_image_resource(image_part: Any, model: DocumentModel) -> str:
    data = image_part.blob
    digest = hashlib.sha256(data).hexdigest()
    resource_id = f"image-{digest[:16]}"
    if resource_id not in model.resources:
        content_type = image_part.content_type
        kind = ResourceKind.VECTOR_IMAGE if content_type in VECTOR_IMAGE_MEDIA_TYPES else ResourceKind.RASTER_IMAGE
        properties: dict[str, Any] = {"sha256": digest}
        if content_type == "image/svg+xml":
            properties["colors"] = svg_color_catalog(data)
        model.add_resource(
            Resource(
                id=resource_id,
                kind=kind,
                media_type=content_type,
                data=data,
                filename=Path(str(image_part.partname)).name,
                properties=properties,
            )
        )
    return resource_id


def _drawing_position(drawing: Any) -> tuple[float, float]:
    if drawing is None:
        return 0.0, 0.0

    def offset(axis: str) -> float:
        values = drawing.xpath(f"./wp:position{axis}/wp:posOffset")
        return emu_to_points(float(values[0].text or 0)) if values else 0.0

    return offset("H"), offset("V")


def _drawing_properties(drawing: Any) -> dict[str, Any]:
    from lxml import etree

    if drawing is None:
        return {}
    placement = etree.QName(drawing).localname
    properties: dict[str, Any] = {"placement": placement}
    if placement != "anchor":
        return properties
    for axis in ("H", "V"):
        positions = drawing.xpath(f"./wp:position{axis}")
        if not positions:
            continue
        position = positions[0]
        prefix = "horizontal" if axis == "H" else "vertical"
        properties[f"{prefix}_relative_from"] = position.get("relativeFrom")
        align = next((child for child in position if etree.QName(child).localname == "align"), None)
        if align is not None:
            properties[f"{prefix}_align"] = align.text
    wrap_element = next(
        (child for child in drawing if etree.QName(child).localname.startswith("wrap")),
        None,
    )
    if wrap_element is not None:
        properties["wrap"] = etree.QName(wrap_element).localname.removeprefix("wrap").lower()
        if wrap_element.get("wrapText") is not None:
            properties["wrap_text"] = wrap_element.get("wrapText")
        polygon = next(
            (child for child in wrap_element if etree.QName(child).localname == "wrapPolygon"),
            None,
        )
        if polygon is not None:
            points = [
                {"x": int(point.get("x", "0")), "y": int(point.get("y", "0"))}
                for point in polygon
                if etree.QName(point).localname in {"start", "lineTo"}
            ]
            properties["wrap_polygon"] = {
                "edited": polygon.get("edited", "0") in {"1", "true", "on"},
                "points": points,
            }
    for source_name, target_name in (
        ("behindDoc", "behind_doc"),
        ("layoutInCell", "layout_in_cell"),
        ("allowOverlap", "allow_overlap"),
        ("relativeHeight", "relative_height"),
    ):
        value = drawing.get(source_name)
        if value is not None:
            properties[target_name] = int(value) if value.isdigit() else value
    return properties


def _drawing_crop(blip: Any) -> ImageCrop | None:
    fill = blip.getparent()
    if fill is None:
        return None
    source_rectangles = fill.xpath("./a:srcRect")
    if not source_rectangles:
        return None
    source = source_rectangles[0]
    return ImageCrop(
        left=int(source.get("l", "0")) / 100000,
        top=int(source.get("t", "0")) / 100000,
        right=int(source.get("r", "0")) / 100000,
        bottom=int(source.get("b", "0")) / 100000,
    )


def _picture_transform(blip: Any) -> Any | None:
    pictures = blip.xpath("ancestor::pic:pic[1]")
    if not pictures:
        return None
    transforms = pictures[0].xpath("./pic:spPr/a:xfrm")
    return transforms[0] if transforms else None


def _drawing_rotation(blip: Any) -> float:
    transform = _picture_transform(blip)
    if transform is None or transform.get("rot") is None:
        return 0.0
    return ooxml_angle_to_degrees(int(transform.get("rot")))


def _drawing_effects(blip: Any, model: DocumentModel) -> dict[str, Any]:
    """Read normalized effects and retain original DrawingML for lossless output."""

    from lxml import etree

    properties: dict[str, Any] = {}
    transform = _picture_transform(blip)
    if transform is not None:
        if transform.get("flipH") is not None:
            properties["flip_horizontal"] = transform.get("flipH") in {"1", "true", "on"}
        if transform.get("flipV") is not None:
            properties["flip_vertical"] = transform.get("flipV") in {"1", "true", "on"}

    effect_nodes = [child for child in blip if etree.QName(child).localname != "extLst"]
    if effect_nodes:
        properties["blip_effects_xml"] = [etree.tostring(child, encoding="unicode") for child in effect_nodes]
    for child in effect_nodes:
        local_name = etree.QName(child).localname
        if local_name == "alphaModFix" and child.get("amt") is not None:
            properties["opacity"] = int(child.get("amt")) / 100000
        elif local_name == "grayscl":
            properties["grayscale"] = True

    pictures = blip.xpath("ancestor::pic:pic[1]")
    shape_properties = pictures[0].xpath("./pic:spPr") if pictures else []
    if not shape_properties:
        return properties
    lines = shape_properties[0].xpath("./a:ln")
    if lines:
        properties["line_xml"] = etree.tostring(lines[0], encoding="unicode")
        solid = next((child for child in lines[0] if etree.QName(child).localname == "solidFill"), None)
        if solid is not None:
            from textalchemy.formats.docx_style import document_theme_colors

            color, metadata = resolve_drawingml_color(solid, document_theme_colors(model))
            if color is not None:
                properties["stroke_color"] = color.to_dict()
                properties["stroke_color_source"] = metadata
    fill = next((child for child in shape_properties[0] if etree.QName(child).localname == "solidFill"), None)
    if fill is not None:
        from textalchemy.formats.docx_style import document_theme_colors

        color, metadata = resolve_drawingml_color(fill, document_theme_colors(model))
        if color is not None:
            properties["fill_color"] = color.to_dict()
            properties["fill_color_source"] = metadata
    shape_effects = shape_properties[0].xpath("./a:effectLst | ./a:effectDag")
    if shape_effects:
        properties["shape_effects_xml"] = etree.tostring(shape_effects[0], encoding="unicode")
    return properties


__all__ = ["read_run_images", "read_run_vml_colors"]
