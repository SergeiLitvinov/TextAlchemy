"""Read SVG companions and cropping without flattening vector resources."""

from textalchemy.core.document_model import Image, ImageCrop

P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
SVG = "{http://schemas.microsoft.com/office/drawing/2016/SVG/main}"


def read_picture(element, slide_part, state, box):
    fill = element.find(P + "blipFill")
    blip = fill.find(A + "blip") if fill is not None else None
    if blip is None:
        return None

    def resource(rid):
        if not rid:
            return None
        try:
            part = slide_part.related_part(rid)
        except (KeyError, ValueError):
            return None
        return state.add_image_resource(media_type=part.content_type, data=part.blob,
                                        filename=str(part.partname).rsplit("/", 1)[-1], object_id=rid)

    primary = resource(blip.get(R + "embed"))
    svg = blip.find(".//" + SVG + "svgBlip")
    vector = resource(svg.get(R + "embed")) if svg is not None else None
    if not (vector or primary):
        return None
    properties = {"fallback_resource_id": primary} if vector and primary else {}
    crop = fill.find(A + "srcRect")
    cropping = ImageCrop(*(float(crop.get(side, "0")) / 100000 for side in ("l", "t", "r", "b"))) if crop is not None else None
    info = element.find(P + "nvPicPr/" + P + "cNvPr")
    return Image(resource_id=vector or primary, alt_text=info.get("descr", "") if info is not None else "",
                 box=box, crop=cropping, properties=properties,
                 provenance=state.origin(object_id=info.get("id") if info is not None else None))
