"""Format-local native geometry and identity needed by the PPTX reverse path."""

from dataclasses import asdict

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"


def shape_geometry(element):
    from lxml import etree

    result = {"has_style": element.find(P + "style") is not None}
    effect = element.find(P + "style/" + A + "effectRef")
    if effect is not None:
        result["effect_ref"] = effect.get("idx")
    nonvisual = element.find(P + "nvSpPr/" + P + "cNvSpPr")
    if nonvisual is not None:
        result["text_box"] = nonvisual.get("txBox", "0") in ("1", "true")
    properties = element.find(P + "spPr")
    if properties is not None:
        for tag in ("prstGeom", "custGeom"):
            geometry = properties.find(A + tag)
            if geometry is not None:
                result["geometry_xml"] = etree.tostring(geometry, encoding="unicode", with_tail=False)
        line = properties.find(A + "ln")
        if line is not None:
            result["line_geometry"] = {
                tag: dict(child.attrib)
                for tag in ("headEnd", "tailEnd", "prstDash", "noFill")
                if (child := line.find(A + tag)) is not None
            }
    connector = element.find(P + "nvCxnSpPr/" + P + "cNvCxnSpPr")
    if connector is not None:
        result["connections"] = {
            tag: dict(child.attrib) for tag in ("stCxn", "endCxn") if (child := connector.find(A + tag)) is not None
        }
    return result


def remember_shape_identity(block, element):
    """Keep ancestry separate from the model's absolute, editable Box."""
    props = block.properties.setdefault("pptx", {})
    info = element.find(".//" + P + "cNvPr")
    if info is not None:
        props["object_id"] = info.get("id")
    groups = []
    for ancestor in element.iterancestors(P + "grpSp"):
        info = ancestor.find(P + "nvGrpSpPr/" + P + "cNvPr")
        if info is not None:
            groups.append({"id": info.get("id"), "name": info.get("name", "")})
    if groups:
        props["groups"] = list(reversed(groups))
    if props.get("transform"):
        props["imported_box"] = asdict(block.box)
