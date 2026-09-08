"""Native paragraph/list and text-frame settings, independent of run writing."""

from textalchemy.core.diagnostics import IssueSeverity

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def configure_frame(frame, block, report, location):
    from lxml import etree
    from pptx.enum.text import MSO_ANCHOR
    from pptx.util import Pt

    settings = block.properties.get("pptx", {}).get("text_frame", {})
    body = frame._txBody.bodyPr
    if "vert" in settings:
        body.set("vert", settings["vert"])
    autofit = settings.get("autofit")
    if autofit:
        mode = autofit.get("mode")
        if mode in ("noAutofit", "normAutofit", "spAutoFit"):
            for child in list(body):
                if child.tag in (A + "noAutofit", A + "normAutofit", A + "spAutoFit"):
                    body.remove(child)
            node = etree.Element(A + mode)
            if mode == "normAutofit":
                for attr in ("fontScale", "lnSpcReduction"):
                    if attr in autofit:
                        node.set(attr, str(autofit[attr]))
            # Autofit follows preset text warp and precedes scene/shape 3D and extensions.
            position = next((i for i, child in enumerate(body) if child.tag != A + "prstTxWarp"), len(body))
            body.insert(position, node)
        else:
            report.add(IssueSeverity.LOSS, "styles", "Неизвестный режим автоподбора текста не перенесён.", location)
    frame.word_wrap = settings.get("wrap", "square") != "none"
    for key, side in (("lIns", "left"), ("rIns", "right"), ("tIns", "top"), ("bIns", "bottom")):
        if key in settings:
            setattr(frame, f"margin_{side}", Pt(settings[key]))
    anchors = {"t": MSO_ANCHOR.TOP, "ctr": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}
    if settings.get("anchor") in anchors:
        frame.vertical_anchor = anchors[settings["anchor"]]
    elif settings.get("anchor"):
        report.add(IssueSeverity.LOSS, "styles", "Вертикальное распределение текста упрощено.", location)


def configure_paragraph(paragraph, block, index):
    from lxml import etree
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Pt

    metadata = block.properties.get("pptx", {}).get("paragraphs", [])
    settings = dict(metadata[index]) if index < len(metadata) else {}
    # Canonical properties override imported paragraph settings when explicitly supplied.
    for key, field in (
        ("marL", "left_indent_pt"),
        ("marR", "right_indent_pt"),
        ("indent", "first_line_indent_pt"),
        ("space_before_pt", "space_before_pt"),
        ("space_after_pt", "space_after_pt"),
        ("line_spacing_pt", "line_spacing_pt"),
        ("line_spacing_pct", "line_spacing"),
    ):
        if block.properties.get(field) is not None:
            settings[key] = block.properties[field]
            if key.startswith("line_spacing"):
                settings.pop("line_spacing_pct" if key.endswith("pt") else "line_spacing_pt", None)
    original_alignment = metadata[0].get("alignment") if metadata else None
    alignment = settings.get("alignment") if index < len(metadata) else block.alignment
    if block.alignment != original_alignment and block.alignment is not None:
        alignment = block.alignment
    paragraph.alignment = {
        "left": PP_ALIGN.LEFT,
        "center": PP_ALIGN.CENTER,
        "right": PP_ALIGN.RIGHT,
        "justify": PP_ALIGN.JUSTIFY,
    }.get(alignment)
    paragraph.level = max(0, min(8, int(settings.get("level", 0))))
    if settings.get("default_font_size_pt") is not None:
        paragraph.font.size = Pt(settings["default_font_size_pt"])
    properties = paragraph._p.get_or_add_pPr()
    for key in ("marL", "marR", "indent", "defTabSz"):
        if key in settings:
            properties.set(key, str(int(Pt(settings[key]))))
    if "tabs" in settings:
        tabs = etree.SubElement(properties, A + "tabLst")
        for tab in settings["tabs"]:
            etree.SubElement(tabs, A + "tab", pos=str(int(Pt(tab["position_pt"]))), algn=tab.get("alignment", "l"))
    for tag, pt_key, ratio_key in (
        ("lnSpc", "line_spacing_pt", "line_spacing_pct"),
        ("spcBef", "space_before_pt", "space_before_pct"),
        ("spcAft", "space_after_pt", "space_after_pct"),
    ):
        if pt_key in settings or ratio_key in settings:
            node = etree.SubElement(properties, A + tag)
            points = pt_key in settings
            value = settings[pt_key if points else ratio_key]
            etree.SubElement(node, A + ("spcPts" if points else "spcPct"), val=str(round(value * (100 if points else 100000))))
    if settings.get("bullet_font"):
        etree.SubElement(properties, A + "buFont", typeface=settings["bullet_font"])
    if settings.get("bullet_none"):
        etree.SubElement(properties, A + "buNone")
    elif settings.get("numbered"):
        attrs = {"type": settings["numbered"]}
        if settings.get("number_start") is not None:
            attrs["startAt"] = str(settings["number_start"])
        etree.SubElement(properties, A + "buAutoNum", **attrs)
    elif settings.get("bullet_char"):
        etree.SubElement(properties, A + "buChar", char=settings["bullet_char"])
    order = {
        tag: index
        for index, tag in enumerate(
            (
                "lnSpc",
                "spcBef",
                "spcAft",
                "buClrTx",
                "buClr",
                "buSzTx",
                "buSzPct",
                "buSzPts",
                "buFontTx",
                "buFont",
                "buNone",
                "buAutoNum",
                "buChar",
                "buBlip",
                "tabLst",
                "defRPr",
                "extLst",
            )
        )
    }
    properties[:] = sorted(properties, key=lambda node: order.get(node.tag.removeprefix(A), 99))
