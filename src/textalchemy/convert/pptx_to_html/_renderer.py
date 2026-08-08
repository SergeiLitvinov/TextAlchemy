"""Convert a .pptx to a self-contained HTML viewer.

Используется через :class:`textalchemy.convert.pptx_to_html.PptxToHtmlConverter`
или :func:`textalchemy.convert.pptx_to_html.convert`.

Точка входа: :func:`convert_pptx` — рендерит один .pptx в указанную директорию.
"""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path
from typing import Optional

from PIL import Image
from pptx import Presentation

from textalchemy.core.io import check_archive_safety

from ._omml import (  # noqa: F401
    M_NS as OMML_NS,
)
from ._omml import (
    convert_omml,
)
from ._omml import (
    has_math as omml_has_math,
)
from ._pptx_lib import (
    EMU_PER_INCH,
    PRST_GEOMETRY,
    color_to_hex,
    emu_to_in,
    fmt,
    qn,
    safe_id,
    size_to_pt,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Resource extraction
# ----------------------------------------------------------------------------
def extract_resources(pptx_path: Path, out_dir: Path):
    """Extract media files and convert WMF/EMF to PNG."""
    check_archive_safety(pptx_path)
    images_dir = out_dir / "assets" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    media_index: dict[str, str] = {}  # rId -> relative URL

    with zipfile.ZipFile(pptx_path) as z:
        names = [n for n in z.namelist() if n.startswith("ppt/media/")]
        for name in names:
            ext = Path(name).suffix.lower()
            base = Path(name).name
            if ext in (".wmf", ".emf"):
                # Pillow reads WMF; EMF is exposed as WMF format internally.
                try:
                    data = z.read(name)
                    im = Image.open(io.BytesIO(data))
                    out_name = Path(base).stem + ".png"
                    im.save(images_dir / out_name, "PNG")
                    media_index[name] = f"assets/images/{out_name}"
                except Exception as e:
                    logger.warning("failed to convert %s: %s", name, e)
                    out_name = base
                    (images_dir / out_name).write_bytes(z.read(name))
                    media_index[name] = f"assets/images/{out_name}"
            else:
                out_name = base
                (images_dir / out_name).write_bytes(z.read(name))
                media_index[name] = f"assets/images/{out_name}"

        # Extract OLE objects (binary)
        ole_dir = out_dir / "assets" / "ole"
        ole_dir.mkdir(parents=True, exist_ok=True)
        for name in z.namelist():
            if name.startswith("ppt/embeddings/") and name.endswith(".bin"):
                base = Path(name).name
                (ole_dir / base).write_bytes(z.read(name))
    return media_index


def resolve_image(media_index: dict[str, str], rels: dict[str, str], rid: str) -> Optional[str]:
    target = rels.get(rid)
    if not target:
        return None
    # rels are relative to the slide XML, e.g. "../media/image1.png"
    if target.startswith("../"):
        norm = "ppt/" + target[3:]
    else:
        norm = target
    return media_index.get(norm)


# ----------------------------------------------------------------------------
# Geometry helpers
# ----------------------------------------------------------------------------
def parse_xfrm(spPr_elem, parent_xfrm=None):
    """Return (left_in, top_in, width_in, height_in, rotation_deg)."""
    if spPr_elem is None:
        if parent_xfrm is not None:
            return parent_xfrm
        return 0, 0, 0, 0, 0
    xfrm = spPr_elem.find(qn("a:xfrm"))
    if xfrm is None:
        if parent_xfrm is not None:
            return parent_xfrm
        return 0, 0, 0, 0, 0
    off = xfrm.find(qn("a:off"))
    ext = xfrm.find(qn("a:ext"))
    rot = xfrm.get("rot", "0")
    rot_deg = int(rot) / 60000.0  # 60000 = 1 degree
    left = int(off.get("x", 0)) if off is not None else 0
    top = int(off.get("y", 0)) if off is not None else 0
    cx = int(ext.get("cx", 0)) if ext is not None else 0
    cy = int(ext.get("cy", 0)) if ext is not None else 0
    return emu_to_in(left), emu_to_in(top), emu_to_in(cx), emu_to_in(cy), rot_deg


def get_ph_position(sp_elem, slide, ph_cache=None):
    """If sp has no xfrm, try to find the position from the slide layout/master."""
    spPr = sp_elem.find(qn("p:spPr"))
    if spPr is not None and spPr.find(qn("a:xfrm")) is not None:
        return None  # has its own xfrm
    nvSpPr = sp_elem.find(qn("p:nvSpPr"))
    if nvSpPr is None:
        return None
    nvPr = nvSpPr.find(qn("p:nvPr"))
    if nvPr is None:
        return None
    ph = nvPr.find(qn("p:ph"))
    if ph is None:
        return None
    ph_type = ph.get("type") or "body"
    ph_idx = ph.get("idx")
    if ph_idx is not None:
        ph_idx = int(ph_idx)
    if ph_cache is None:
        ph_cache = get_placeholder_xfrm(slide)
    # Look up in cache: try (type, idx) first, then (type, None), then idx only
    candidates = [
        (ph_type, ph_idx),
        (ph_type, None),
    ]
    if ph_idx is not None:
        # Try matching any type with this idx
        for (t, i), v in ph_cache.items():
            if i == ph_idx:
                return v
    for key in candidates:
        if key in ph_cache:
            return ph_cache[key]
    return None


# ----------------------------------------------------------------------------
# Shape rendering
# ----------------------------------------------------------------------------
def get_fill(sp_elem):
    """Return fill dict: {type:'solid'|'gradient', color, opacity} or None."""
    spPr = sp_elem.find(qn("p:spPr"))
    if spPr is None:
        return None
    fill = spPr.find(qn("a:solidFill"))
    if fill is not None:
        color = color_to_hex(fill)
        # alpha from inside solidFill
        alpha = 1.0
        for ch in fill:
            a = ch.find(qn("a:alpha"))
            if a is not None:
                alpha = int(a.get("val")) / 100000.0
        if color:
            return {"type": "solid", "color": color, "alpha": alpha}
    grad = spPr.find(qn("a:gradFill"))
    if grad is not None:
        stops = []
        for gs in grad.findall(qn("a:gsLst") + "/" + qn("a:gs")):
            pos = int(gs.get("pos", 0)) / 100000.0
            color = color_to_hex(gs)
            if color:
                alpha_el = gs.find(qn("a:srgbClr") + "/" + qn("a:alpha"))
                if alpha_el is None:
                    alpha_el = gs.find(qn("a:schemeClr") + "/" + qn("a:alpha"))
                alpha = (int(alpha_el.get("val")) / 100000.0) if alpha_el is not None else 1.0
                stops.append({"pos": pos, "color": color, "alpha": alpha})
        if stops:
            return {"type": "gradient", "stops": stops,
                    "angle": int(grad.find(qn("a:lin")).get("ang", 0)) / 60000.0
                            if grad.find(qn("a:lin")) is not None else 0}
    return None


def get_line(sp_elem):
    spPr = sp_elem.find(qn("p:spPr"))
    if spPr is None:
        return None
    ln = spPr.find(qn("a:ln"))
    if ln is None:
        return None
    width_emu = int(ln.get("w", 0))
    width_pt = max(0.75, width_emu / 12700.0)  # 12700 EMU = 1 pt; floor at 0.75pt for visibility
    color = None
    if ln.find(qn("a:solidFill")) is not None:
        color = color_to_hex(ln.find(qn("a:solidFill")))
    if not color:
        color = "#333333"  # default dark gray if no explicit color
    dash = ln.find(qn("a:prstDash"))
    dash_arr = dash.get("val") if dash is not None else None
    # End arrowhead
    tail = ln.find(qn("a:tailEnd"))
    head = ln.find(qn("a:headEnd"))
    tail_type = tail.get("type") if tail is not None and tail.get("type") not in (None, "none") else None
    head_type = head.get("type") if head is not None and head.get("type") not in (None, "none") else None
    return {"color": color, "width_pt": width_pt, "dash": dash_arr,
            "head": head_type, "tail": tail_type}


def build_path_for_prst(prst: str, avLst=None) -> Optional[str]:
    """Get a path-d string for a preset geometry, with adjustments from avLst."""
    entry = PRST_GEOMETRY.get(prst)
    if entry is None:
        return None
    d, _path_only = entry
    # For now, don't apply avLst adjustments (e.g., corner radius for roundRect)
    return d


def render_shape_svg(sp_elem, width_in, height_in, xfrm_pos, fill_info, line_info):
    """Build SVG markup for a sp element. Returns an inner SVG string."""
    spPr = sp_elem.find(qn("p:spPr"))
    if spPr is None:
        return ""
    prst = spPr.find(qn("a:prstGeom"))
    if prst is None:
        cust = spPr.find(qn("a:custGeom"))
        if cust is not None:
            return render_custgeom(cust, width_in, height_in, fill_info, line_info)
        return ""
    prst_name = prst.get("prst", "rect")
    d = build_path_for_prst(prst_name)
    if d is None:
        # Unknown preset; fall back to a rect (preserves bounding box)
        d = PRST_GEOMETRY["rect"][0]
        prst_name = "rect"

    # Special-case line geometry
    if prst_name in ("line", "straightConnector1"):
        stroke = (line_info or {}).get("color", "#000000")
        sw = (line_info or {}).get("width_pt", 1)
        dash = (line_info or {}).get("dash")
        dash_attr = f' stroke-dasharray="{"4 3" if dash=="dash" else "1 2" if dash=="dot" else "8 2 2 2" if dash=="dashDot" else "8 2 2 2 2 2" if dash=="lgDashDotDot" else ""}"' if dash else ""
        markers = build_arrow_markers(line_info)
        # Use the xfrm to determine line endpoints within the bounding box.
        # pptx: xfrm/off is the line's start, xfrm/ext is the (dx,dy) to the end.
        # flips/rotation come from the xfrm.
        if isinstance(xfrm_pos, tuple) and len(xfrm_pos) == 5:
            _left, _t, _w_in, _h_in, _rot_deg = xfrm_pos
        else:
            _left, _t, _w_in, _h_in, _rot_deg = 0, 0, width_in, height_in, 0
        sp_pr = sp_elem.find(qn("p:spPr"))
        xfrm = sp_pr.find(qn("a:xfrm")) if sp_pr is not None else None
        if xfrm is not None:
            cx = int(xfrm.find(qn("a:ext")).get("cx", 0))
            cy = int(xfrm.find(qn("a:ext")).get("cy", 0))
            # Compute line endpoints in 0..100 viewBox
            # cx,cy are the offset to the end relative to off
            # The bounding box width/height in EMU
            _box_cx = abs(cx) or 1
            _box_cy = abs(cy) or 1
            # Normalize endpoints to bbox in 0..100
            if cx == 0 and cy != 0:
                # vertical line
                y1 = 0 if cy > 0 else 100
                y2 = 100 if cy > 0 else 0
                x1, x2 = 0, 0
            elif cy == 0 and cx != 0:
                # horizontal line
                x1 = 0 if cx > 0 else 100
                x2 = 100 if cx > 0 else 0
                y1, y2 = 0, 0
            else:
                # diagonal - use sign of cx,cy to pick quadrant
                x1 = 0 if cx > 0 else 100
                y1 = 0 if cy > 0 else 100
                x2 = 100 if cx > 0 else 0
                y2 = 100 if cy > 0 else 0
        else:
            x1, y1, x2, y2 = 0, 50, 100, 50
        # viewBox 0..100 with line endpoints. preserveAspectRatio="none" so it
        # stretches to the bounding box.
        return (f'<svg viewBox="0 0 100 100" preserveAspectRatio="none" '
                f'width="100%" height="100%" class="line-svg">{markers}'
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
                f'stroke-width="{max(0.5, sw)}" '
                f'{"stroke-linecap=round" if sw < 3 else ""}'
                f'{dash_attr} '
                f'{arrow_marker_attrs(line_info)}/></svg>')

    # Build a fill / stroke description
    fill = "none"
    opacity = 1.0
    if fill_info:
        if fill_info.get("type") == "solid":
            c = fill_info["color"]
            opacity = fill_info.get("alpha", 1.0)
            fill = c
        elif fill_info.get("type") == "gradient":
            stops = fill_info["stops"]
            parts = [f'<stop offset="{s["pos"]*100:.0f}%" stop-color="{s["color"]}" stop-opacity="{s["alpha"]}"/>' for s in stops]
            angle = fill_info.get("angle", 0)
            # Map pptx angle (60000ths of degree, measured from x-axis) to CSS angle
            css_angle = (90 - angle) % 360
            grad_id = f"g{safe_id(sp_elem.get('id') or 'x')}"
            defs = (f'<defs><linearGradient id="{grad_id}" '
                    f'gradientTransform="rotate({css_angle:.2f})">{"".join(parts)}'
                    f'</linearGradient></defs>')
            stroke = ''
            if line_info:
                stroke = f' stroke="{line_info["color"]}" stroke-width="{line_info["width_pt"]}"'
            return (f'<svg viewBox="0 0 100 100" preserveAspectRatio="none" '
                    f'width="100%" height="100%">'
                    f'{defs}'
                    f'<path d="{d}" fill="url(#{grad_id})"{stroke}/></svg>')

    stroke_attrs = ""
    if line_info:
        stroke_attrs = f' stroke="{line_info["color"]}" stroke-width="{line_info["width_pt"]}"'

    return (f'<svg viewBox="0 0 100 100" preserveAspectRatio="none" '
            f'width="100%" height="100%">'
            f'<path d="{d}" fill="{fill}" fill-opacity="{opacity}"{stroke_attrs}/></svg>')


def render_custgeom(cust, width_in, height_in, fill_info, line_info):
    """Render a custom geometry (a:custGeom). Coordinates are in 0..1 viewBox."""
    paths = []
    for pathl in cust.findall(qn("a:pathLst") + "/" + qn("a:path")):
        d = ""
        w = int(pathl.get("w", 0))
        _h = int(pathl.get("h", 0))
        # w/h give the path's intrinsic size; we map to 0..1 in viewBox
        # Note: pptx path commands use absolute EMU-like values; we'll scale
        # by 1/max(w, h) to fit the viewBox.
        scale = 1.0 / max(1, w)
        for cmd in pathl:
            tag = cmd.tag.split("}")[-1]
            if tag == "moveTo":
                pt = cmd.find(qn("a:pt"))
                x = float(pt.get("x", 0)) * scale
                y = float(pt.get("y", 0)) * scale
                d += f"M{x:.4f},{y:.4f} "
            elif tag == "lnTo":
                pt = cmd.find(qn("a:pt"))
                x = float(pt.get("x", 0)) * scale
                y = float(pt.get("y", 0)) * scale
                d += f"L{x:.4f},{y:.4f} "
            elif tag == "arcTo":
                w_a = float(cmd.get("wArc", 0)) * scale
                h_a = float(cmd.get("hArc", 0)) * scale
                stAng = float(cmd.get("stAng", 0)) / 60000.0
                swAng = float(cmd.get("swAng", 0)) / 60000.0
                pt = cmd.find(qn("a:pt"))
                ex = float(pt.get("x", 0)) * scale
                ey = float(pt.get("y", 0)) * scale
                # Convert arc to SVG; pptx arc angles are in degrees from x-axis, CCW
                d += f"A{w_a:.4f},{h_a:.4f} {stAng:.2f} "
                d += "1 " if swAng >= 0 else "0 "
                d += f"{ex:.4f},{ey:.4f} "
            elif tag == "cubicBezTo":
                pts = cmd.findall(qn("a:pt"))
                if len(pts) >= 3:
                    coords = " ".join(f"{float(p.get('x',0))*scale:.4f},{float(p.get('y',0))*scale:.4f}" for p in pts)
                    d += f"C{coords} "
            elif tag == "quadBezTo":
                pts = cmd.findall(qn("a:pt"))
                if len(pts) >= 2:
                    coords = " ".join(f"{float(p.get('x',0))*scale:.4f},{float(p.get('y',0))*scale:.4f}" for p in pts)
                    d += f"Q{coords} "
            elif tag == "close":
                d += "Z "
        paths.append(d.strip())
    d_all = " ".join(paths)
    fill = "none"
    if fill_info and fill_info.get("type") == "solid":
        fill = fill_info["color"]
    stroke_attrs = ""
    if line_info:
        stroke_attrs = f' stroke="{line_info["color"]}" stroke-width="{line_info["width_pt"]}"'
    return (f'<svg viewBox="0 0 1 1" preserveAspectRatio="none" '
            f'width="100%" height="100%">'
            f'<path d="{d_all}" fill="{fill}"{stroke_attrs}/></svg>')


def build_arrow_markers(line_info):
    if not line_info:
        return ""
    head = line_info.get("head")
    tail = line_info.get("tail")
    out = ""
    if head and head in ("triangle", "arrow", "stealth", "diamond", "oval"):
        out += f'<marker id="ar-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{line_info["color"]}"/></marker>'
    if tail and tail in ("triangle", "arrow", "stealth", "diamond", "oval"):
        out += f'<marker id="ar-tail" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M10,0 L0,5 L10,10 z" fill="{line_info["color"]}"/></marker>'
    return f'<defs>{out}</defs>'


def arrow_marker_attrs(line_info):
    if not line_info:
        return ""
    attrs = []
    if line_info.get("head"):
        attrs.append('marker-end="url(#ar-head)"')
    if line_info.get("tail"):
        attrs.append('marker-start="url(#ar-tail)"')
    return " " + " ".join(attrs)


# ----------------------------------------------------------------------------
# Text rendering
# ----------------------------------------------------------------------------
def render_text_body(txBody_elem, placeholder_type=None) -> str:
    """Render an a:txBody element as HTML."""
    if txBody_elem is None:
        return ""
    bodyPr = txBody_elem.find(qn("a:bodyPr"))
    # anchor
    anchor = "top"
    _wrap = "square"
    if bodyPr is not None:
        a = bodyPr.get("anchor")
        if a == "ctr":
            anchor = "middle"
        elif a == "b":
            anchor = "bottom"
        wt = bodyPr.get("wrap")
        if wt == "none":
            _wrap = "none"
        elif wt == "square":
            _wrap = "square"
    lIns = int(bodyPr.get("lIns", 91440)) / 914400.0 if bodyPr is not None else 0.1
    tIns = int(bodyPr.get("tIns", 45720)) / 914400.0 if bodyPr is not None else 0.05
    rIns = int(bodyPr.get("rIns", 91440)) / 914400.0 if bodyPr is not None else 0.1
    bIns = int(bodyPr.get("bIns", 45720)) / 914400.0 if bodyPr is not None else 0.05

    paragraphs = []
    for p in txBody_elem.findall(qn("a:p")):
        paragraphs.append(render_paragraph(p))
    style = (f"padding:{tIns:.3f}in {rIns:.3f}in {bIns:.3f}in {lIns:.3f}in;"
             f"display:flex;flex-direction:column;justify-content:{ 'flex-start' if anchor=='top' else 'center' if anchor=='middle' else 'flex-end' };"
             f"box-sizing:border-box;")
    return (f'<div class="tx-body" style="{style}">'
            + "".join(paragraphs)
            + "</div>")


def render_paragraph(p) -> str:
    pPr = p.find(qn("a:pPr"))
    align = "left"
    _indent_l = 0.0
    indent_first = 0.0
    bullet_char = None
    bullet_color = None
    bullet_font = None
    marL = 0.0
    if pPr is not None:
        a = pPr.get("algn")
        if a == "ctr":
            align = "center"
        elif a == "r":
            align = "right"
        elif a == "just":
            align = "justify"
        marL = int(pPr.get("marL", 0)) / 914400.0
        indent = int(pPr.get("indent", 0)) / 914400.0
        if indent < 0:
            indent_first = -indent
        bu = pPr.find(qn("a:buChar"))
        if bu is not None:
            bullet_char = bu.get("char")
        bfa = pPr.find(qn("a:buFont"))
        if bfa is not None:
            bullet_font = bfa.get("typeface")
        buc = pPr.find(qn("a:buClr"))
        if buc is not None:
            bullet_color = color_to_hex(buc)
        buAutoNum = pPr.find(qn("a:buAutoNum"))
        if buAutoNum is not None:
            bullet_char = "•"  # fallback; ideally render number style

    # If the paragraph contains OMML, render it as a math paragraph
    has_m = omml_has_math(p)
    if has_m:
        return render_paragraph_with_math(p, align, marL, indent_first, bullet_char, bullet_color, bullet_font)

    runs_html = []
    for child in p:
        tag = child.tag.split("}")[-1]
        if tag == "r":
            runs_html.append(render_run(child))
        elif tag == "br":
            runs_html.append("<br>")
        elif tag == "fld":
            # text fields (slide number, date)
            txt = "".join((t.text or "") for t in child.findall(".//" + qn("a:t")))
            rpr = child.find(qn("a:rPr"))
            style = run_style(rpr) if rpr is not None else ""
            runs_html.append(f'<span style="{style}">{html_escape(txt)}</span>')
        elif tag == "endParaRPr":
            pass  # paragraph end marker, no content
    style = f"text-align:{align};padding-left:{marL:.3f}in;padding-right:0;text-indent:{indent_first:.3f}in;margin:0;"

    # Bullet prefix
    bullet_html = ""
    if bullet_char:
        bc = bullet_color or "currentColor"
        bfont = bullet_font or "inherit"
        bullet_html = f'<span class="bullet" style="color:{bc};font-family:{bfont};margin-right:0.2em;">{html_escape(bullet_char)}</span>'

    return f'<p style="{style}">{bullet_html}{"".join(runs_html)}</p>'


def render_paragraph_with_math(p, align, marL, indent_first, bullet_char, bullet_color, bullet_font) -> str:
    """Render an <a:p> paragraph that contains OMML <m:oMath> blocks.

    Strategy: build a single <math> element from the paragraph's children in
    document order. Each <m:oMath> becomes a nested <m:oMath> in MathML (well,
    it's flattened to <mrow> or top-level constructs); each <a:r> between math
    blocks becomes an <mtext> or <mo> depending on its content.
    """
    return _render_paragraph_with_math_impl(p, align, marL, indent_first, bullet_char, bullet_color, bullet_font)


def _render_paragraph_with_math_impl(p, align, marL, indent_first, bullet_char, bullet_color, bullet_font) -> str:
    from lxml import etree as _etree
    MATH_NS = "http://www.w3.org/1998/Math/MathML"
    # Build a math element with proper namespace
    math = _etree.Element("{%s}math" % MATH_NS, nsmap={None: MATH_NS})

    # Helper to add text run to math
    def add_text_run(r_elem):
        rpr = r_elem.find(qn("a:rPr"))
        # Get text
        txt = "".join((t.text or "") for t in r_elem.findall(qn("a:t")))
        if not txt:
            return
        # Decide tag: mo if all operator chars, mtext otherwise
        ops = set("+-−=<>≤≥≠≈±×·⋅÷∗∗∘⨂⨀∑∏∫∮∝∈∉⊂⊃∩∪∧∨¬→↔⇒⇐↦∀∃∅∇∂′″‴‰°")
        if all(c in ops for c in txt.strip()) and txt.strip():
            tag = "mo"
        else:
            tag = "mtext"
        m = _etree.SubElement(math, "{%s}%s" % (MATH_NS, tag))
        m.text = txt
        if rpr is not None:
            sz = rpr.get("sz")
            if sz:
                m.set("mathsize", f"{int(sz)/100:.0f}pt")
            if rpr.get("i") in ("1", "true"):
                m.set("mathvariant", "italic")

    def add_omath(o_elem):
        # Pass the lxml element directly (convert_omml handles elements)
        sub_math_str = convert_omml(o_elem)
        if not sub_math_str:
            return
        sub_math = _etree.fromstring(sub_math_str.encode("utf-8"))
        for ch in list(sub_math):
            math.append(ch)

    for child in p:
        local = child.tag.split("}")[-1]
        if local == "r":
            add_text_run(child)
        elif local == "oMath":
            add_omath(child)
        elif local == "m":
            # a14:m container - find the oMath or oMathPara inside
            omath_inner = child.find("{%s}oMath" % OMML_NS)
            if omath_inner is None:
                # Try oMathPara
                ompara = child.find("{%s}oMathPara" % OMML_NS)
                if ompara is not None:
                    omath_inner = ompara.find("{%s}oMath" % OMML_NS)
            if omath_inner is not None:
                add_omath(omath_inner)
        elif local == "pPr":
            pass
        elif local == "endParaRPr":
            pass
        elif local == "br":
            _etree.SubElement(math, "mspace", linebreak="newline")

    math_html = _etree.tostring(math, encoding="unicode", method="html")
    # etree.tostring with method="html" doesn't add xmlns to root; ensure it does
    if not math_html.startswith("<math"):
        math_html = math_html.replace("<math", '<math xmlns="http://www.w3.org/1998/Math/MathML"', 1)
    # Wrap in <p> for layout consistency with non-math paragraphs
    p_style = f"text-align:{align};padding-left:{marL:.3f}in;padding-right:0;text-indent:{indent_first:.3f}in;margin:0;"
    bullet_html = ""
    if bullet_char:
        bc = bullet_color or "currentColor"
        bfont = bullet_font or "inherit"
        bullet_html = f'<span class="bullet" style="color:{bc};font-family:{bfont};margin-right:0.2em;">{html_escape(bullet_char)}</span>'
    return f'<p class="math-p" style="{p_style}">{bullet_html}{math_html}</p>'


def render_run(r) -> str:
    rpr = r.find(qn("a:rPr"))
    t = r.find(qn("a:t"))
    text = t.text if t is not None and t.text is not None else ""
    style = run_style(rpr) if rpr is not None else ""
    return f'<span style="{style}">{html_escape(text)}</span>'


def run_style(rpr) -> str:
    s = []
    sz = rpr.get("sz")
    if sz:
        s.append(f"font-size:{size_to_pt(sz)}")
    b = rpr.get("b")
    if b and b != "0":
        s.append("font-weight:bold")
    it = rpr.get("i")
    if it and it != "0":
        s.append("font-style:italic")
    u = rpr.get("u")
    if u and u != "none":
        s.append("text-decoration:underline")
        if u == "sng":
            pass
        elif u == "dbl":
            s[-1] = "text-decoration:underline double"
    strike = rpr.get("strike")
    if strike and strike != "noStrike":
        s.append("text-decoration:line-through")
    # baseline superscript/subscript
    baseline = rpr.get("baseline")
    if baseline:
        v = int(baseline) / 1000.0  # -30000=subscript, 30000=superscript
        if v > 0:
            s.append("vertical-align:super")
            s.append("font-size:smaller")
        else:
            s.append("vertical-align:sub")
            s.append("font-size:smaller")
    # fonts
    latin = rpr.find(qn("a:latin"))
    if latin is not None:
        tf = latin.get("typeface")
        if tf:
            s.append(f"font-family:'{tf}',Arial,sans-serif")
    # fill
    fill = rpr.find(qn("a:solidFill"))
    if fill is not None:
        color = color_to_hex(fill)
        if color:
            s.append(f"color:{color}")
    # highlight
    hl = rpr.find(qn("a:highlight"))
    if hl is not None:
        c = color_to_hex(hl)
        if c:
            s.append(f"background-color:{c}")
    return ";".join(s)


def html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ----------------------------------------------------------------------------
# Slide rendering
# ----------------------------------------------------------------------------
def render_slide(slide, slide_num: int, media_index, slide_rels, slide_size_in) -> str:
    """Return an HTML string for a single slide."""
    spTree = slide.element.find(qn("p:cSld") + "/" + qn("p:spTree"))
    if spTree is None:
        return ""

    parts = []

    # Background
    bg = slide.element.find(qn("p:cSld") + "/" + qn("p:bg"))
    if bg is not None:
        bg_html = render_background(bg, slide_rels, media_index, slide_size_in)
        if bg_html:
            parts.append(bg_html)

    # Iterate shapes (top-level + groups handled inline)
    for child in spTree:
        tag = child.tag.split("}")[-1]
        if tag == "sp":
            html = render_sp(child, media_index, slide_rels, slide)
            if html:
                parts.append(html)
        elif tag == "pic":
            html = render_pic(child, media_index, slide_rels, slide)
            if html:
                parts.append(html)
        elif tag == "grpSp":
            html = render_grpSp(child, media_index, slide_rels, slide)
            if html:
                parts.append(html)
        elif tag == "graphicFrame":
            html = render_graphicFrame(child, media_index, slide_rels, slide)
            if html:
                parts.append(html)
        elif tag == "cxnSp":
            # connector (line) - reuse sp renderer since structure is identical
            html = render_sp(child, media_index, slide_rels, slide)
            if html:
                parts.append(html)
        elif tag == "AlternateContent":
            # mc:AlternateContent: pick the Choice branch (modern content)
            MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
            choice = child.find("{%s}Choice" % MC_NS)
            if choice is not None:
                for sub in choice:
                    sub_tag = sub.tag.split("}")[-1]
                    if sub_tag == "sp":
                        html = render_sp(sub, media_index, slide_rels, slide)
                        if html:
                            parts.append(html)
                    elif sub_tag == "pic":
                        html = render_pic(sub, media_index, slide_rels, slide)
                        if html:
                            parts.append(html)
        elif tag in ("nvGrpSpPr", "grpSpPr"):
            pass  # ignore
        else:
            # unknown
            pass

    inner = "".join(parts)
    return f'<section class="slide" data-slide="{slide_num}">{inner}</section>'


def render_background(bg, slide_rels, media_index, slide_size_in) -> str:
    bgPr = bg.find(qn("p:bgPr"))
    if bgPr is None:
        return ""
    # Image background
    blipFill = bgPr.find(qn("a:blipFill"))
    if blipFill is not None:
        blip = blipFill.find(qn("a:blip"))
        if blip is not None:
            rid = blip.get(qn("r:embed"))
            url = resolve_image(media_index, slide_rels, rid)
            if url:
                w, h = slide_size_in
                return f'<div class="bg-image" style="position:absolute;left:0;top:0;width:{w:.2f}in;height:{h:.2f}in;background:url({url}) center/cover no-repeat;"></div>'
    # Solid fill background
    solid = bgPr.find(qn("a:solidFill"))
    if solid is not None:
        c = color_to_hex(solid)
        if c:
            w, h = slide_size_in
            return f'<div class="bg-solid" style="position:absolute;left:0;top:0;width:{w:.2f}in;height:{h:.2f}in;background:{c};"></div>'
    return ""


def render_sp(sp, media_index, slide_rels, slide=None) -> str:
    spPr = sp.find(qn("p:spPr"))
    left, top, w, h, rot = parse_xfrm(spPr)
    if (w <= 0 or h <= 0) and slide is not None:
        ph_pos = get_ph_position(sp, slide)
        if ph_pos is not None:
            left, top, w, h, rot = ph_pos
    txBody = sp.find(qn("p:txBody"))
    has_text = txBody is not None and (txBody.find(qn("a:p")) is not None or
                                       txBody.find(qn("a:p") + "/" + qn("a:r")) is not None or
                                       txBody.find(".//" + qn("a:t")) is not None)
    if w <= 0 or h <= 0:
        if not has_text:
            return ""  # skip empty shape with no xfrm
        # Text shape with no xfrm: give it a default size at top-left of slide
        w = 13.33
        h = 2.0
        if left == 0 and top == 0:
            left = 0.5
            top = 0.5
    fill = get_fill(sp)
    line = get_line(sp)
    txBody = sp.find(qn("p:txBody"))
    # If shape has text, place SVG (if any) and a text overlay
    has_text = txBody is not None and (txBody.find(qn("a:p")) is not None or
                                       txBody.find(qn("a:p") + "/" + qn("a:r")) is not None or
                                       txBody.find(".//" + qn("a:t")) is not None)
    pos = f"position:absolute;left:{fmt(left)}in;top:{fmt(top)}in;width:{fmt(w)}in;height:{fmt(h)}in;"
    if rot:
        pos += f"transform:rotate({rot:.2f}deg);"

    if has_text and fill is None and line is None:
        # text-only
        return f'<div class="shape text-only" style="{pos}">{render_text_body(txBody)}</div>'

    svg = render_shape_svg(sp, w, h, (left, top, w, h, rot), fill, line)
    if not has_text:
        return f'<div class="shape" style="{pos}">{svg}</div>'

    # Shape with text on top
    return (
        f'<div class="shape" style="{pos}">'
        + svg
        + f'<div class="text-overlay" style="position:absolute;inset:0;">{render_text_body(txBody)}</div>'
        + '</div>'
    )


def render_pic(pic, media_index, slide_rels, slide=None) -> str:
    spPr = pic.find(qn("p:spPr"))
    left, top, w, h, rot = parse_xfrm(spPr)
    if (w <= 0 or h <= 0) and slide is not None:
        ph_pos = get_ph_position(pic, slide)
        if ph_pos is not None:
            left, top, w, h, rot = ph_pos
    if w <= 0 or h <= 0:
        return ""
    blipFill = pic.find(qn("p:blipFill"))
    blip = blipFill.find(qn("a:blip")) if blipFill is not None else None
    if blip is None:
        return ""
    rid = blip.get(qn("r:embed"))
    url = resolve_image(media_index, slide_rels, rid)
    if not url:
        return ""
    pos = f"position:absolute;left:{fmt(left)}in;top:{fmt(top)}in;width:{fmt(w)}in;height:{fmt(h)}in;"
    if rot:
        pos += f"transform:rotate({rot:.2f}deg);"
    return f'<img class="pic" style="{pos}" src="{url}" alt=""/>'


def render_grpSp(grp, media_index, slide_rels, slide=None) -> str:
    spPr = grp.find(qn("p:grpSpPr"))
    if spPr is None:
        return ""
    xfrm = spPr.find(qn("a:xfrm"))
    if xfrm is None:
        return ""
    off = xfrm.find(qn("a:off"))
    ext = xfrm.find(qn("a:ext"))
    chOff = xfrm.find(qn("a:chOff"))
    chExt = xfrm.find(qn("a:chExt"))
    rot = float(xfrm.get("rot", 0)) / 60000.0
    gx = int(off.get("x", 0))
    gy = int(off.get("y", 0))
    gcx = int(ext.get("cx", 1))
    gcy = int(ext.get("cy", 1))
    cox = int(chOff.get("x", 0))
    coy = int(chOff.get("y", 0))
    ccx = int(chExt.get("cx", 1))
    ccy = int(chExt.get("cy", 1))
    sx = gcx / ccx
    sy = gcy / ccy
    # Group positioning in CSS
    left = emu_to_in(gx)
    top = emu_to_in(gy)
    w = emu_to_in(gcx)
    h = emu_to_in(gcy)
    pos = f"position:absolute;left:{fmt(left)}in;top:{fmt(top)}in;width:{fmt(w)}in;height:{fmt(h)}in;"
    if rot:
        pos += f"transform:rotate({rot:.2f}deg);"

    parts = []
    for ch in grp:
        tag = ch.tag.split("}")[-1]
        if tag == "sp":
            # Adjust children's xfrm by group transform: child xfrm is in chOff..chExt space
            spPr_ch = ch.find(qn("p:spPr"))
            xfrm_ch = spPr_ch.find(qn("a:xfrm")) if spPr_ch is not None else None
            if xfrm_ch is not None:
                off_ch = xfrm_ch.find(qn("a:off"))
                ext_ch = xfrm_ch.find(qn("a:ext"))
                if off_ch is not None and ext_ch is not None:
                    cx = int(off_ch.get("x", 0))
                    cy = int(off_ch.get("y", 0))
                    cwx = int(ext_ch.get("cx", 0))
                    cwy = int(ext_ch.get("cy", 0))
                    # Map to group local coords
                    new_x = (cx - cox) * sx
                    new_y = (cy - coy) * sy
                    new_w = cwx * sx
                    new_h = cwy * sy
                    # Replace xfrm values
                    off_ch.set("x", str(int(new_x)))
                    off_ch.set("y", str(int(new_y)))
                    ext_ch.set("cx", str(int(new_w)))
                    ext_ch.set("cy", str(int(new_h)))
            parts.append(render_sp(ch, media_index, slide_rels))
        elif tag == "pic":
            # Same coordinate transform
            spPr_ch = ch.find(qn("p:spPr"))
            xfrm_ch = spPr_ch.find(qn("a:xfrm")) if spPr_ch is not None else None
            if xfrm_ch is not None:
                off_ch = xfrm_ch.find(qn("a:off"))
                ext_ch = xfrm_ch.find(qn("a:ext"))
                if off_ch is not None and ext_ch is not None:
                    cx = int(off_ch.get("x", 0))
                    cy = int(off_ch.get("y", 0))
                    cwx = int(ext_ch.get("cx", 0))
                    cwy = int(ext_ch.get("cy", 0))
                    new_x = (cx - cox) * sx
                    new_y = (cy - coy) * sy
                    new_w = cwx * sx
                    new_h = cwy * sy
                    off_ch.set("x", str(int(new_x)))
                    off_ch.set("y", str(int(new_y)))
                    ext_ch.set("cx", str(int(new_w)))
                    ext_ch.set("cy", str(int(new_h)))
            parts.append(render_pic(ch, media_index, slide_rels))
    inner = "".join(parts)
    return f'<div class="group" style="{pos}">{inner}</div>'


def render_graphicFrame(gf, media_index, slide_rels, slide=None) -> str:
    """Render a p:graphicFrame - can contain table or OLE-with-image-fallback."""
    xfrm = gf.find(qn("p:xfrm"))
    if xfrm is None:
        return ""
    off = xfrm.find(qn("a:off"))
    ext = xfrm.find(qn("a:ext"))
    left = emu_to_in(int(off.get("x", 0)))
    top = emu_to_in(int(off.get("y", 0)))
    w = emu_to_in(int(ext.get("cx", 0)))
    h = emu_to_in(int(ext.get("cy", 0)))
    pos = f"position:absolute;left:{fmt(left)}in;top:{fmt(top)}in;width:{fmt(w)}in;height:{fmt(h)}in;"

    # OLE / embedded object
    ole = gf.find(".//" + qn("p:graphicData") + "/" + qn("p:oleObj"))
    if ole is not None:
        # find blip inside graphicData (fallback image)
        blip = gf.find(".//" + qn("a:blip"))
        if blip is not None:
            rid = blip.get(qn("r:embed"))
            url = resolve_image(media_index, slide_rels, rid)
            if url:
                return f'<img class="pic ole" style="{pos}object-fit:contain;" src="{url}" alt=""/>'
        return ""

    # Table
    table = gf.find(".//" + qn("a:tbl"))
    if table is not None:
        return render_table(table, pos, w, h)

    return ""


def render_table(tbl, pos, w, h) -> str:
    rows = tbl.findall(qn("a:tr"))
    html_rows = []
    col_widths = []
    grid = tbl.find(qn("a:tblGrid"))
    if grid is not None:
        col_widths = [int(gc.get("w", 0)) / 914400.0 for gc in grid.findall(qn("a:gridCol"))]
    for tr in rows:
        height = int(tr.get("h", 0)) / 914400.0
        cells_html = []
        for tc in tr.findall(qn("a:tc")):
            # cell properties
            tcPr = tc.find(qn("a:tcPr"))
            fill_color = None
            gridSpan = 1
            if tcPr is not None:
                gridSpan = int(tcPr.get("gridSpan", 1))
                sf = tcPr.find(qn("a:solidFill"))
                if sf is not None:
                    fill_color = color_to_hex(sf)
            # cell text
            txbody = tc.find(qn("a:txBody"))
            text = render_text_body(txbody) if txbody is not None else ""
            bg = f"background:{fill_color};" if fill_color else ""
            attrs = f' style="{bg}padding:0.05in;"'
            if gridSpan > 1:
                attrs += f' colspan="{gridSpan}"'
            cells_html.append(f'<td{attrs}>{text}</td>')
        rh = f"height:{fmt(height)}in;" if height else ""
        html_rows.append(f'<tr style="{rh}">{"".join(cells_html)}</tr>')
    grid_cols = "".join(f'<col style="width:{fmt(cw)}in;">' for cw in col_widths)
    return (f'<div class="shape" style="{pos}"><table class="pp-table" '
            f'style="width:100%;height:100%;border-collapse:collapse;font-size:0.2in;">'
            f'<colgroup>{grid_cols}</colgroup>{"".join(html_rows)}</table></div>')


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def get_slide_rels(pptx_path: Path, slide_part):
    """Get a dict of {rId: target} for a slide's rels file."""
    # Access via the part
    rels = {}
    for rel in slide_part.rels.values():
        if not rel.is_external:
            rels[rel.rId] = rel.target_ref
    return rels


def get_placeholder_xfrm(slide):
    """Look up the inherited xfrm for placeholders that have no own xfrm.

    Returns dict {(ph_type_str, idx): (left, top, w, h, rot)} from the layout/master.
    Keys use the XML string type names like "title", "body", "sldNum", "dt", "ftr".
    """
    cache = getattr(slide, "_ph_xfrm_cache", None)
    if cache is not None:
        return cache
    cache = {}
    # Walk layout -> master for placeholder positions
    layout = slide.slide_layout
    for sp in layout.shapes:
        if sp.is_placeholder:
            ph = sp.placeholder_format
            xml_type = ph_type_to_xml(ph.type)
            key = (xml_type, ph.idx)
            key2 = (xml_type, None)
            if sp.left is not None and sp.top is not None:
                val = (emu_to_in(sp.left), emu_to_in(sp.top),
                       emu_to_in(sp.width or 0), emu_to_in(sp.height or 0),
                       (sp.rotation or 0))
                cache[key] = val
                cache.setdefault(key2, val)
    # Also try master
    try:
        master = layout.slide_master
        for sp in master.shapes:
            if sp.is_placeholder:
                ph = sp.placeholder_format
                xml_type = ph_type_to_xml(ph.type)
                key = (xml_type, ph.idx)
                key2 = (xml_type, None)
                if sp.left is not None and sp.top is not None:
                    val = (emu_to_in(sp.left), emu_to_in(sp.top),
                           emu_to_in(sp.width or 0), emu_to_in(sp.height or 0),
                           (sp.rotation or 0))
                    cache.setdefault(key, val)
                    cache.setdefault(key2, val)
    except Exception:
        pass
    slide._ph_xfrm_cache = cache
    return cache


def ph_type_to_xml(ph_type):
    """Map python-pptx PP_PLACEHOLDER_TYPE enum to XML type string."""
    from pptx.enum.shapes import PP_PLACEHOLDER_TYPE
    return {
        PP_PLACEHOLDER_TYPE.TITLE: "title",
        PP_PLACEHOLDER_TYPE.BODY: "body",
        PP_PLACEHOLDER_TYPE.OBJECT: "object",
        PP_PLACEHOLDER_TYPE.SLIDE_NUMBER: "sldNum",
        PP_PLACEHOLDER_TYPE.FOOTER: "ftr",
        PP_PLACEHOLDER_TYPE.DATE: "dt",
        PP_PLACEHOLDER_TYPE.CENTER_TITLE: "ctrTitle",
        PP_PLACEHOLDER_TYPE.SUBTITLE: "subTitle",
    }.get(ph_type, "body")


def convert_pptx(pptx_path: str | Path, out_dir: str | Path) -> None:
    """Главная точка входа: рендерит ``pptx_path`` в ``out_dir``.

    Создаёт ``index.html``, ``assets/images/``, ``assets/ole/``,
    ``assets/css/main.css``, ``assets/js/main.js``.
    """
    pptx = Path(pptx_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "assets" / "images").mkdir(parents=True, exist_ok=True)
    (out / "assets" / "ole").mkdir(parents=True, exist_ok=True)
    (out / "assets" / "css").mkdir(parents=True, exist_ok=True)
    (out / "assets" / "js").mkdir(parents=True, exist_ok=True)

    logger.info("Loading %s...", pptx)
    media_index = extract_resources(pptx, out)
    logger.info("Extracted %d media files", len(media_index))

    prs = Presentation(str(pptx))
    sw = prs.slide_width
    sh = prs.slide_height
    assert sw is not None and sh is not None
    sw_in = sw / EMU_PER_INCH
    sh_in = sh / EMU_PER_INCH
    logger.info("Slide size: %.2f x %.2f in", sw_in, sh_in)

    slides_html = []
    titles = []
    slides = list(prs.slides)
    for i, slide in enumerate(slides, 1):
        rels = get_slide_rels(pptx, slide.part)
        html = render_slide(slide, i, media_index, rels, (sw_in, sh_in))
        slides_html.append(html)
        # Title text for sidebar
        title = extract_title(slide)
        titles.append(title)
        if i % 10 == 0:
            logger.info("rendered %d/%d", i, len(slides))

    logger.info("Writing index.html...")
    write_index(out, slides_html, titles, (sw_in, sh_in))
    write_css(out)
    write_js(out)
    logger.info("Done")


# Backwards-compat alias (использовался в старом cli-скрипте)
main = convert_pptx


def extract_title(slide) -> str:
    """Try to extract a short title from the slide for the sidebar."""
    for sh in slide.shapes:
        if not sh.has_text_frame:
            continue
        txt = sh.text_frame.text.strip()
        if txt and sh.name and "Заголовок" in sh.name or "Title" in (sh.name or "") or "title" in (sh.name or "").lower():
            return txt[:60].replace("\n", " ")
        if txt and len(txt) < 200:
            return txt[:60].replace("\n", " ")
    return ""


CSS = r"""
:root {
  --bg: #1a1a1a;
  --fg: #eaeaea;
  --sidebar-bg: #0e0e0e;
  --sidebar-fg: #c8c8c8;
  --accent: #5B9BD5;
  --slide-bg: #ffffff;
  --slide-fg: #000000;
  --border: #2a2a2a;
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0; height: 100%;
  background: var(--bg);
  color: var(--fg);
  font-family: -apple-system, "Segoe UI", Arial, sans-serif;
  overflow: hidden;
}
#layout { display: flex; height: 100vh; }
#sidebar {
  width: 260px;
  background: var(--sidebar-bg);
  border-right: 1px solid var(--border);
  overflow-y: auto;
  flex-shrink: 0;
}
#sidebar h1 { font-size: 13px; margin: 0; padding: 12px 14px; color: var(--accent); font-weight: 600; }
#sidebar .counter { padding: 0 14px 8px; color: #777; font-size: 12px; }
#sidebar ul { list-style: none; margin: 0; padding: 0; }
#sidebar li {
  padding: 6px 14px;
  cursor: pointer;
  border-left: 3px solid transparent;
  color: var(--sidebar-fg);
  font-size: 12px;
  line-height: 1.4;
}
#sidebar li:hover { background: #1f1f1f; }
#sidebar li.active {
  background: #1a2a3a;
  border-left-color: var(--accent);
  color: #fff;
}
#sidebar li .num { color: #666; margin-right: 6px; font-variant-numeric: tabular-nums; }

#main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
#toolbar {
  height: 36px; padding: 0 12px;
  display: flex; align-items: center; gap: 12px;
  background: #181818; border-bottom: 1px solid var(--border);
  font-size: 12px;
}
#toolbar button {
  background: #2a2a2a; color: #ddd; border: 1px solid #3a3a3a;
  padding: 4px 10px; border-radius: 3px; cursor: pointer; font-size: 12px;
}
#toolbar button:hover { background: #3a3a3a; }
#toolbar .spacer { flex: 1; }
#toolbar input[type=range] { width: 100px; }

#stage {
  flex: 1; overflow: auto;
  display: flex; align-items: center; justify-content: center;
  padding: 20px; background: #0a0a0a;
}
#stage-wrap { transform-origin: center center; }
.slide {
  position: relative;
  background: var(--slide-bg);
  color: var(--slide-fg);
  box-shadow: 0 4px 24px rgba(0,0,0,0.5);
  overflow: hidden;
  display: none;
}
.slide.active { display: block; }
.shape { position: absolute; }
.shape.text-only .tx-body { width: 100%; height: 100%; }
.text-overlay { display: flex; }
.text-overlay .tx-body { width: 100%; height: 100%; }
.tx-body p { margin: 0; line-height: 1.15; }
.tx-body span { white-space: pre-wrap; }
.pic { position: absolute; }
.bg-image, .bg-solid { position: absolute; left: 0; top: 0; pointer-events: none; }
.pp-table { border-collapse: collapse; }
.pp-table td, .pp-table th { border: 1px solid #999; padding: 0.05in; vertical-align: middle; }
.line-svg { position: absolute; inset: 0; }

/* Math paragraphs - inline math from MathJax */
.math-p { line-height: 1.4; }
.math-p mjx-container { margin: 0 2px; vertical-align: middle; }

/* Editor mode */
body.edit-mode .slide.active { outline: 2px solid var(--accent); }
body.edit-mode .shape, body.edit-mode .pic, body.edit-mode .group, body.edit-mode .text-overlay {
  outline: 1px dashed rgba(91,155,213,0.3);
  cursor: pointer;
}
body.edit-mode .shape:hover, body.edit-mode .pic:hover, body.edit-mode .group:hover {
  outline: 1px solid var(--accent);
}
body.edit-mode .shape.selected, body.edit-mode .pic.selected, body.edit-mode .group.selected,
body.edit-mode .bg-image.selected, body.edit-mode .bg-solid.selected {
  outline: 2px solid #ff9800 !important;
  cursor: move;
}

/* Editor panel */
#editor {
  position: fixed;
  right: -340px;
  top: 60px;
  width: 320px;
  background: #181818;
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  padding: 12px;
  color: #ddd;
  font-size: 12px;
  transition: right 0.2s ease;
  z-index: 100;
  box-shadow: 0 4px 16px rgba(0,0,0,0.5);
}
#editor.open { right: 16px; }
#editor .ed-header {
  display: flex; justify-content: space-between; align-items: center;
  font-weight: 600; color: var(--accent); margin-bottom: 10px;
  border-bottom: 1px solid #333; padding-bottom: 6px;
}
#editor .ed-close {
  background: none; border: none; color: #aaa; font-size: 18px; cursor: pointer;
  padding: 0 6px;
}
#editor .ed-close:hover { color: #fff; }
#editor .ed-row { display: flex; gap: 6px; margin-bottom: 6px; }
#editor label { display: flex; flex-direction: column; flex: 1; gap: 2px; }
#editor input, #editor textarea {
  background: #2a2a2a; color: #eee;
  border: 1px solid #3a3a3a; border-radius: 3px;
  padding: 4px 6px; font-size: 12px;
  font-family: inherit;
}
#editor textarea { resize: vertical; min-height: 60px; }
#editor .ed-buttons { display: flex; gap: 6px; margin-top: 10px; }
#editor .ed-buttons button {
  flex: 1; background: #2a2a2a; color: #ddd;
  border: 1px solid #3a3a3a; padding: 6px; border-radius: 3px;
  cursor: pointer; font-size: 12px;
}
#editor .ed-buttons button:hover { background: #3a3a3a; }
#editor .ed-apply { background: #1e4d6b !important; }
#editor .ed-save { background: #1e6b3a !important; }

.ed-flash {
  position: fixed; top: 50px; right: 20px;
  background: #1e6b3a; color: white;
  padding: 8px 16px; border-radius: 4px;
  font-size: 13px; z-index: 200;
  box-shadow: 0 2px 8px rgba(0,0,0,0.4);
  animation: fadeOut 1.5s ease forwards;
}
@keyframes fadeOut {
  0%, 60% { opacity: 1; }
  100% { opacity: 0; }
}
"""

JS = r"""
const slides = document.querySelectorAll('.slide');
const list = document.getElementById('slide-list');
const counter = document.getElementById('counter');
const stage = document.getElementById('stage');
const wrap = document.getElementById('stage-wrap');

let current = 1;
let total = slides.length;
let scale = 1.0;

function goto(n, push=true) {
  n = Math.max(1, Math.min(total, n));
  if (n === current && !push) {
    show();
    return;
  }
  current = n;
  if (push) {
    history.replaceState(null, '', '#' + n);
  }
  show();
}

function show() {
  slides.forEach(s => s.classList.remove('active'));
  const s = document.querySelector(`.slide[data-slide="${current}"]`);
  if (s) s.classList.add('active');
  // highlight sidebar
  document.querySelectorAll('#slide-list li').forEach(li => li.classList.remove('active'));
  const li = document.querySelector(`#slide-list li[data-slide="${current}"]`);
  if (li) {
    li.classList.add('active');
    li.scrollIntoView({ block: 'nearest' });
  }
  counter.textContent = current + ' / ' + total;
  rescale();
  // re-typeset math
  if (window.MathJax && window.MathJax.typesetPromise) {
    window.MathJax.typesetPromise([s]);
  }
}

function rescale() {
  const s = document.querySelector('.slide.active');
  if (!s) return;
  // Reset to intrinsic slide size (set in style by width:N in; height:N in;)
  const sw = s.offsetWidth, sh = s.offsetHeight;
  const avw = stage.clientWidth - 40, avh = stage.clientHeight - 40;
  const f = Math.min(avw / sw, avh / sh, 4);
  s.style.zoom = (f * scale).toFixed(4);
}

document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') { goto(current + 1); e.preventDefault(); }
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { goto(current - 1); e.preventDefault(); }
  else if (e.key === 'Home') { goto(1); e.preventDefault(); }
  else if (e.key === 'End') { goto(total); e.preventDefault(); }
  else if (e.key === 'e' || e.key === 'E') { document.body.classList.toggle('edit-mode'); }
  else if (e.key === '+' || e.key === '=') { scale = Math.min(4, scale * 1.1); rescale(); }
  else if (e.key === '-' || e.key === '_') { scale = Math.max(0.2, scale / 1.1); rescale(); }
  else if (e.key === '0') { scale = 1.0; rescale(); }
  else if (e.key === 'f' || e.key === 'F') { toggleFullscreen(); }
});

function toggleFullscreen() {
  const s = document.querySelector('.slide.active');
  if (s && s.requestFullscreen) s.requestFullscreen();
  else if (document.fullscreenElement) document.exitFullscreen();
}

list.addEventListener('click', e => {
  const li = e.target.closest('li[data-slide]');
  if (li) goto(parseInt(li.dataset.slide, 10));
});

window.addEventListener('resize', rescale);
window.addEventListener('hashchange', () => {
  const n = parseInt(location.hash.slice(1), 10);
  if (!isNaN(n)) goto(n, false);
});

// ============================================================
// Edit mode
// ============================================================
const editor = document.getElementById('editor');
const STORAGE_KEY = 'pptx2html:edits';
let selectedShape = null;
let savedEdits = {};  // { "slide_N": { shapeId: {left, top, width, height, rotation, html} } }

function loadEdits() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) savedEdits = JSON.parse(raw);
  } catch (e) {
    savedEdits = {};
  }
}

function saveEdits() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(savedEdits));
  } catch (e) {
    console.warn('Failed to save edits:', e);
  }
}

function shapeId(shape) {
  // Use a stable id: index within slide + tag
  const slide = shape.closest('.slide');
  if (!slide) return null;
  const all = Array.from(slide.querySelectorAll('.shape, .pic, .group, .bg-image, .bg-solid'));
  const idx = all.indexOf(shape);
  return idx;
}

function parseStyleNum(style, prop) {
  const m = style.match(new RegExp(prop + ':\\s*(-?[0-9.]+)in'));
  return m ? parseFloat(m[1]) : 0;
}

function getShapeInfo(shape) {
  const cs = shape.style;
  const left = parseStyleNum(cs.cssText, 'left') || parseStyleNum(cs.left, 'left') || 0;
  const top = parseStyleNum(cs.cssText, 'top') || parseStyleNum(cs.top, 'top') || 0;
  const width = parseStyleNum(cs.cssText, 'width') || parseStyleNum(cs.width, 'width') || 0;
  const height = parseStyleNum(cs.cssText, 'height') || parseStyleNum(cs.height, 'height') || 0;
  let rotation = 0;
  const rotM = cs.cssText.match(/transform:\s*rotate\(([0-9.-]+)deg\)/);
  if (rotM) rotation = parseFloat(rotM[1]);
  // Text content: pick the tx-body or pic or innerHTML
  let text = '';
  if (shape.classList.contains('pic') || shape.classList.contains('ole')) {
    text = shape.getAttribute('alt') || shape.getAttribute('src') || '';
  } else {
    const tx = shape.querySelector('.tx-body') || shape.querySelector('.text-overlay .tx-body');
    if (tx) text = tx.innerText || tx.textContent || '';
    else text = shape.innerText || '';
  }
  const id = shapeId(shape);
  return { id, left, top, width, height, rotation, text, tag: shape.tagName.toLowerCase(), classes: shape.className };
}

function applyShapeEdits(slideEl, idx, edits) {
  const shape = Array.from(slideEl.querySelectorAll('.shape, .pic, .group, .bg-image, .bg-solid'))[idx];
  if (!shape) return;
  // We have to be careful: the inline style has many properties. We'll preserve the original
  // style attribute and modify only what we know about.
  if (edits.left !== undefined) shape.style.left = edits.left + 'in';
  if (edits.top !== undefined) shape.style.top = edits.top + 'in';
  if (edits.width !== undefined) shape.style.width = edits.width + 'in';
  if (edits.height !== undefined) shape.style.height = edits.height + 'in';
  if (edits.rotation !== undefined) {
    // Replace or add transform: rotate
    const m = shape.style.cssText.match(/transform:\s*rotate\([0-9.-]+deg\)/);
    if (m) {
      shape.style.cssText = shape.style.cssText.replace(/transform:\s*rotate\([0-9.-]+deg\)/, `transform:rotate(${edits.rotation}deg)`);
    } else if (edits.rotation !== 0) {
      shape.style.transform = `rotate(${edits.rotation}deg)`;
    }
  }
  if (edits.text !== undefined) {
    const tx = shape.querySelector('.tx-body') || shape.querySelector('.text-overlay .tx-body');
    if (tx) {
      // Replace the whole tx-body. Use plain text -> wrap in <p>.
      const lines = edits.text.split(/\n/);
      const pHtml = lines.map(l => `<p>${escapeHtml(l)}</p>`).join('');
      tx.innerHTML = pHtml;
    } else if (shape.classList.contains('pic') || shape.classList.contains('ole')) {
      shape.setAttribute('alt', edits.text);
    }
  }
}

function restoreEdits() {
  for (const key of Object.keys(savedEdits)) {
    const m = key.match(/^slide_(\d+)$/);
    if (!m) continue;
    const slideEl = document.querySelector(`.slide[data-slide="${m[1]}"]`);
    if (!slideEl) continue;
    const edits = savedEdits[key];
    for (const idxStr of Object.keys(edits)) {
      applyShapeEdits(slideEl, parseInt(idxStr, 10), edits[idxStr]);
    }
  }
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function selectShape(shape) {
  if (selectedShape) selectedShape.classList.remove('selected');
  selectedShape = shape;
  if (!shape) {
    editor.classList.remove('open');
    return;
  }
  selectedShape.classList.add('selected');
  const info = getShapeInfo(shape);
  editor.innerHTML = `
    <div class="ed-header">
      <span>${info.classes.split(' ')[0] || 'shape'}</span>
      <button class="ed-close" onclick="selectShape(null)">×</button>
    </div>
    <div class="ed-row">
      <label>X (in) <input type="number" step="0.01" id="ed-left" value="${info.left.toFixed(3)}"></label>
      <label>Y (in) <input type="number" step="0.01" id="ed-top" value="${info.top.toFixed(3)}"></label>
    </div>
    <div class="ed-row">
      <label>W (in) <input type="number" step="0.01" id="ed-width" value="${info.width.toFixed(3)}"></label>
      <label>H (in) <input type="number" step="0.01" id="ed-height" value="${info.height.toFixed(3)}"></label>
    </div>
    <div class="ed-row">
      <label>Rot (°) <input type="number" step="0.5" id="ed-rot" value="${info.rotation.toFixed(2)}"></label>
    </div>
    ${info.classes.includes('pic') || info.classes.includes('ole') ?
      `<label>alt <input type="text" id="ed-alt" value="${escapeHtml(info.text)}"></label>`
      :
      `<label>Текст <textarea id="ed-text" rows="4">${escapeHtml(info.text)}</textarea></label>`
    }
    <div class="ed-buttons">
      <button class="ed-apply">Применить</button>
      <button class="ed-save">Сохранить</button>
    </div>
  `;
  editor.classList.add('open');
  // Wire up apply
  const apply = () => {
    const left = parseFloat(document.getElementById('ed-left').value);
    const top = parseFloat(document.getElementById('ed-top').value);
    const width = parseFloat(document.getElementById('ed-width').value);
    const height = parseFloat(document.getElementById('ed-height').value);
    const rot = parseFloat(document.getElementById('ed-rot').value);
    const textEl = document.getElementById('ed-text') || document.getElementById('ed-alt');
    const text = textEl ? textEl.value : undefined;
    applyShapeEdits(shape.closest('.slide'), info.id, { left, top, width, height, rotation: rot, text });
    rescale();
    if (window.MathJax && window.MathJax.typesetPromise) {
      window.MathJax.typesetPromise([shape.closest('.slide')]);
    }
  };
  editor.querySelector('.ed-apply').onclick = apply;
  editor.querySelector('.ed-save').onclick = () => {
    apply();
    const key = `slide_${current}`;
    if (!savedEdits[key]) savedEdits[key] = {};
    // Merge with current values
    const fresh = getShapeInfo(shape);
    savedEdits[key][info.id] = {
      left: fresh.left, top: fresh.top, width: fresh.width, height: fresh.height,
      rotation: fresh.rotation, text: fresh.text,
    };
    saveEdits();
    flashSaved();
  };
}

function flashSaved() {
  const f = document.createElement('div');
  f.className = 'ed-flash';
  f.textContent = '✓ Сохранено';
  document.body.appendChild(f);
  setTimeout(() => f.remove(), 1500);
}

// Edit-mode click handler
document.addEventListener('click', e => {
  if (!document.body.classList.contains('edit-mode')) return;
  if (e.target.closest('#editor')) return;  // ignore clicks inside the editor
  if (e.target.closest('#toolbar')) return;
  if (e.target.closest('#sidebar')) return;
  // Walk up to find a shape
  let t = e.target;
  while (t && t !== document.body) {
    if (t.classList && (
      t.classList.contains('shape') || t.classList.contains('pic') ||
      t.classList.contains('group') || t.classList.contains('bg-image') ||
      t.classList.contains('bg-solid') || t.classList.contains('ole')
    )) {
      selectShape(t);
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    t = t.parentElement;
  }
  selectShape(null);
});

// Drag-to-move
let drag = null;
document.addEventListener('mousedown', e => {
  if (!document.body.classList.contains('edit-mode')) return;
  if (!selectedShape) return;
  if (e.target.closest('#editor')) return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  // Only start drag if click was on selected shape itself
  if (e.target !== selectedShape && !selectedShape.contains(e.target)) return;
  const info = getShapeInfo(selectedShape);
  drag = {
    shape: selectedShape,
    startX: e.clientX,
    startY: e.clientY,
    origLeft: info.left,
    origTop: info.top,
    slideRect: selectedShape.closest('.slide').getBoundingClientRect(),
  };
  e.preventDefault();
});

document.addEventListener('mousemove', e => {
  if (!drag) return;
  // Convert pixel delta to inches
  const sw = parseFloat(selectedShape.closest('.slide').style.width);
  const slideW = drag.slideRect.width;
  const dxIn = (e.clientX - drag.startX) * (sw / slideW);
  const dyIn = (e.clientY - drag.startY) * (sw / slideW);
  drag.shape.style.left = (drag.origLeft + dxIn).toFixed(3) + 'in';
  drag.shape.style.top = (drag.origTop + dyIn).toFixed(3) + 'in';
});

document.addEventListener('mouseup', () => {
  if (drag) {
    // Update editor inputs
    const info = getShapeInfo(drag.shape);
    if (document.getElementById('ed-left')) document.getElementById('ed-left').value = info.left.toFixed(3);
    if (document.getElementById('ed-top')) document.getElementById('ed-top').value = info.top.toFixed(3);
    drag = null;
  }
});

// Reset/clear edits
window.resetEdits = function() {
  if (!confirm('Сбросить все правки и перезагрузить?')) return;
  localStorage.removeItem(STORAGE_KEY);
  location.reload();
};
window.exportHTML = function() {
  // Get the current slide's outer HTML
  const html = document.documentElement.outerHTML;
  const blob = new Blob([html], { type: 'text/html' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'index-edited.html';
  a.click();
};

// Initial load
loadEdits();
restoreEdits();

const start = parseInt(location.hash.slice(1), 10);
goto(isNaN(start) ? 1 : start, false);
"""


def write_index(out: Path, slides_html: list[str], titles: list[str], size):
    sw, sh = size
    swf = f"{sw:.4f}".rstrip("0").rstrip(".")
    shf = f"{sh:.4f}".rstrip("0").rstrip(".")
    items = []
    for i, t in enumerate(titles, 1):
        label = t if t else f"Слайд {i}"
        items.append(f'<li data-slide="{i}"><span class="num">{i:03d}</span>{html_escape(label)}</li>')
    list_html = "".join(items)
    slides_block = "\n".join(slides_html)
    # First slide is shown by default
    html = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Презентация</title>
<link rel="stylesheet" href="assets/css/main.css">
<script>
window.MathJax = {{
  tex: {{ inlineMath: [['$', '$'], ['\\\\(', '\\\\)']] }},
  svg: {{ fontCache: 'global' }},
  startup: {{ typeset: false }}
}};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" id="MathJax-script" async></script>
</head>
<body>
<div id="layout">
  <aside id="sidebar">
    <h1>Слайды</h1>
    <div class="counter" id="counter">1 / {len(slides_html)}</div>
    <ul id="slide-list">
      {list_html}
    </ul>
  </aside>
  <main id="main">
    <div id="toolbar">
      <button onclick="goto(current - 1)">‹</button>
      <button onclick="goto(current + 1)">›</button>
      <span class="spacer"></span>
      <label>Масштаб <input type="range" min="0.3" max="4" step="0.05" value="1" oninput="scale=parseFloat(this.value);rescale()"></label>
      <button onclick="document.body.classList.toggle('edit-mode')">Правка</button>
      <button onclick="exportHTML()">Экспорт</button>
      <button onclick="resetEdits()">Сброс</button>
      <button onclick="toggleFullscreen()">⛶</button>
    </div>
    <div id="stage">
      <div id="stage-wrap">
        <style>
          .slide {{ width: {swf}in; height: {shf}in; }}
        </style>
        {slides_block}
      </div>
    </div>
  </main>
  <aside id="editor"></aside>
</div>
<script src="assets/js/main.js"></script>
</body>
</html>
"""
    from textalchemy.core.io import atomic_write_text

    atomic_write_text(out / "index.html", html, encoding="utf-8")


def write_css(out: Path):
    (out / "assets" / "css" / "main.css").write_text(CSS, encoding="utf-8")


def write_js(out: Path):
    (out / "assets" / "js" / "main.js").write_text(JS, encoding="utf-8")
