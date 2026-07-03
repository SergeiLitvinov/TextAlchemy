"""Convert a .pptx file to a self-contained HTML viewer.

Usage: uv run python scripts/convert.py <pptx_path> <output_dir>
"""
from __future__ import annotations

import re
from typing import Optional

# ----------------------------------------------------------------------------
# Namespaces
# ----------------------------------------------------------------------------
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "v": "urn:schemas-microsoft-com:vml",
    "o": "urn:schemas-microsoft-com:office:office",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "a14": "http://schemas.microsoft.com/office/drawing/2010/main",
}
A = "{%s}" % NS["a"]
P = "{%s}" % NS["p"]
R = "{%s}" % NS["r"]
V = "{%s}" % NS["v"]
OFFICE_NS = "{%s}" % NS["o"]


def qn(t: str) -> str:
    pfx, local = t.split(":")
    return "{%s}%s" % (NS[pfx], local)


# ----------------------------------------------------------------------------
# Geometry helpers
# ----------------------------------------------------------------------------
EMU_PER_INCH = 914400
EMU_PER_PX = 914400 / 96  # CSS px at 96 dpi


def emu_to_in(emu) -> float:
    if emu is None:
        return 0.0
    return int(emu) / EMU_PER_INCH


def fmt(v: float) -> str:
    """Compact inch value for CSS."""
    return f"{v:.4f}".rstrip("0").rstrip(".")


def pos_style(left_in, top_in, width_in, height_in, rotation=0.0) -> str:
    s = f"left:{fmt(left_in)}in;top:{fmt(top_in)}in;width:{fmt(width_in)}in;height:{fmt(height_in)}in"
    if rotation:
        # PPT rotation is counter-clockwise positive; CSS rotate is clockwise.
        # They agree on the visual rotation in the same direction in browsers
        # because PPTX uses a left-handed system. Empirically, just use the
        # same numeric value.
        s += f";transform:rotate({rotation:.2f}deg);transform-origin:center"
    return s


# ----------------------------------------------------------------------------
# Color helpers
# ----------------------------------------------------------------------------
THEME_COLORS = {
    "bg1": "#FFFFFF",
    "tx1": "#000000",
    "bg2": "#E7E6E6",
    "tx2": "#44546A",
    "accent1": "#5B9BD5",
    "accent2": "#ED7D31",
    "accent3": "#A5A5A5",
    "accent4": "#FFC000",
    "accent5": "#4472C4",
    "accent6": "#70AD47",
    "hlink": "#0563C1",
    "folHlink": "#954F72",
}


def color_to_hex(elem) -> Optional[str]:
    """Resolve an a:srgbClr or a:schemeClr to a #RRGGBB string."""
    if elem is None:
        return None
    srgb = elem.find(qn("a:srgbClr"))
    if srgb is not None:
        return "#" + srgb.get("val").upper()
    sch = elem.find(qn("a:schemeClr"))
    if sch is not None:
        name = sch.get("val")
        # Apply lumMod/lumOff/tint/shade modifiers
        base = THEME_COLORS.get(name)
        if base is None:
            return None
        lm = sch.find(qn("a:lumMod"))
        lo = sch.find(qn("a:lumOff"))
        shd = sch.find(qn("a:shade"))
        tint = sch.find(qn("a:tint"))
        r, g, b = int(base[1:3], 16), int(base[3:5], 16), int(base[5:7], 16)
        if lm is not None or lo is not None or shd is not None or tint is not None:
            # Convert to HSL, apply, convert back (approximate)
            r2, g2, b2 = apply_lum(r / 255.0, g / 255.0, b / 255.0,
                                    lm_val=float(lm.get("val")) / 100000 if lm is not None else 1.0,
                                    lo_val=float(lo.get("val")) / 100000 if lo is not None else 0.0,
                                    shd_val=float(shd.get("val")) / 100000 if shd is not None else 1.0,
                                    tint_val=float(tint.get("val")) / 100000 if tint is not None else 0.0)
            r, g, b = r2, g2, b2
        return "#{:02X}{:02X}{:02X}".format(max(0, min(255, r)),
                                            max(0, min(255, g)),
                                            max(0, min(255, b)))
    sys_clr = elem.find(qn("a:sysClr"))
    if sys_clr is not None:
        last = sys_clr.get("lastClr")
        if last:
            return "#" + last.upper()
    return None


def apply_lum(r, g, b, lm_val=1.0, lo_val=0.0, shd_val=1.0, tint_val=0.0):
    """Apply PowerPoint lumMod/lumOff/shade/tint to an RGB triple (0-1 floats)."""
    # lumMod multiplies L, lumOff adds to L after multiplication
    if lm_val != 1.0 or lo_val != 0.0:
        h, lightness, s = rgb_to_hls(r, g, b)
        lightness = max(0.0, min(1.0, lightness * lm_val + lo_val))
        r, g, b = hls_to_rgb(h, lightness, s)
    # shade: multiply by shd_val (typically in [0..1])
    if shd_val != 1.0:
        r *= shd_val
        g *= shd_val
        b *= shd_val
    # tint: lighten toward white by tint_val
    if tint_val != 0.0:
        r = r + (1.0 - r) * tint_val
        g = g + (1.0 - g) * tint_val
        b = b + (1.0 - b) * tint_val
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def rgb_to_hls(r, g, b):
    mx = max(r, g, b)
    mn = min(r, g, b)
    lightness = (mx + mn) / 2
    if mx == mn:
        h = s = 0.0
    else:
        d = mx - mn
        s = d / (2 - mx - mn) if lightness > 0.5 else d / (mx + mn)
        if mx == r:
            h = (g - b) / d + (6 if g < b else 0)
        elif mx == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        h /= 6
    return h, lightness, s


def hls_to_rgb(h, lightness, s):
    if s == 0:
        return lightness, lightness, lightness
    q = lightness * (1 + s) if lightness < 0.5 else lightness + s - lightness * s
    p = 2 * lightness - q
    return _hue_to_rgb(p, q, h + 1 / 3), _hue_to_rgb(p, q, h), _hue_to_rgb(p, q, h - 1 / 3)


def _hue_to_rgb(p, q, t):
    if t < 0:
        t += 1
    if t > 1:
        t -= 1
    if t < 1 / 6:
        return p + (q - p) * 6 * t
    if t < 1 / 2:
        return q
    if t < 2 / 3:
        return p + (q - p) * (2 / 3 - t) * 6
    return p


# ----------------------------------------------------------------------------
# Font / size helpers
# ----------------------------------------------------------------------------
def size_to_pt(sz) -> str:
    if sz is None:
        return ""
    # sz in pptx is hundredths of a point
    return f"{int(sz) / 100:.0f}pt"


def safe_id(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", s)[:60]


# ----------------------------------------------------------------------------
# Preset shape -> SVG path mapping (only the common ones)
# ----------------------------------------------------------------------------
# Each entry: prstGeom/@prst -> SVG path-d (in 0..1 viewBox), plus
# a flag whether to draw with a fill.
# Reference: ECMA-376, DrawingML preset shape definitions.
PRST_GEOMETRY = {
    "rect": ("M0,0 L1,0 L1,1 L0,1 Z", False),
    "roundRect": ("M0.05,0 L0.95,0 A0.05,0.05 0 0 1 1,0.05 L1,0.95 A0.05,0.05 0 0 1 0.95,1 L0.05,1 A0.05,0.05 0 0 1 0,0.95 L0,0.05 A0.05,0.05 0 0 1 0.05,0 Z", False),  # noqa: E501
    "ellipse": ("M0.5,0 A0.5,0.5 0 1 0 0.5,1 A0.5,0.5 0 1 0 0.5,0 Z", False),
    "oval": ("M0.5,0 A0.5,0.5 0 1 0 0.5,1 A0.5,0.5 0 1 0 0.5,0 Z", False),
    "triangle": ("M0.5,0 L1,1 L0,1 Z", False),
    "rtTriangle": ("M0,0 L1,0 L1,1 Z", False),
    "diamond": ("M0.5,0 L1,0.5 L0.5,1 L0,0.5 Z", False),
    "parallelogram": ("M0.15,0 L1,0 L0.85,1 L0,1 Z", False),
    "trapezoid": ("M0.1,0 L0.9,0 L1,1 L0,1 Z", False),
    "pentagon": ("M0.5,0 L1,0.38 L0.81,1 L0.19,1 L0,0.38 Z", False),
    "hexagon": ("M0.25,0 L0.75,0 L1,0.5 L0.75,1 L0.25,1 L0,0.5 Z", False),
    "octagon": ("M0.3,0 L0.7,0 L1,0.3 L1,0.7 L0.7,1 L0.3,1 L0,0.7 L0,0.3 Z", False),
    "star5": ("M0.5,0 L0.61,0.35 L0.98,0.35 L0.69,0.6 L0.79,0.95 L0.5,0.75 L0.21,0.95 L0.31,0.6 L0.02,0.35 L0.39,0.35 Z", False),
    "star6": ("M0.5,0 L0.62,0.2 L0.88,0.1 L0.88,0.4 L1,0.6 L0.78,0.7 L0.75,0.95 L0.5,0.85 L0.25,0.95 L0.22,0.7 L0,0.6 L0.12,0.4 L0.12,0.1 L0.38,0.2 Z", False),  # noqa: E501
    "rightArrow": ("M0,0.3 L0.7,0.3 L0.7,0 L1,0.5 L0.7,1 L0.7,0.7 L0,0.7 Z", False),
    "leftArrow": ("M1,0.3 L0.3,0.3 L0.3,0 L0,0.5 L0.3,1 L0.3,0.7 L1,0.7 Z", False),
    "upArrow": ("M0.3,1 L0.3,0.3 L0,0.3 L0.5,0 L1,0.3 L0.7,0.3 L0.7,1 Z", False),
    "downArrow": ("M0.3,0 L0.3,0.7 L0,0.7 L0.5,1 L1,0.7 L0.7,0.7 L0.7,0 Z", False),
    "leftRightArrow": ("M0,0.5 L0.2,0.3 L0.2,0.4 L0.8,0.4 L0.8,0.3 L1,0.5 L0.8,0.7 L0.8,0.6 L0.2,0.6 L0.2,0.7 Z", False),
    "curvedRightArrow": ("M0,0.5 L0.15,0.35 L0.15,0.45 L0.7,0.45 A0.3,0.3 0 1 1 0.4,0.45 L0.55,0.6 L0.2,0.75 A0.5,0.5 0 1 0 0.7,0.25 L0.85,0.4 L0.85,0.5 L0.7,0.65 Z", False),  # noqa: E501
    "callout1": ("M0,0 L1,0 L1,0.7 L0.4,0.7 L0.2,1 L0.2,0.7 L0,0.7 Z", False),
    "callout2": ("M0,0 L1,0 L1,0.7 L0.6,0.7 L0.55,1 L0.4,0.7 L0,0.7 Z", False),
    "cloud": ("M0.2,0.5 A0.2,0.25 0 0 1 0.5,0.4 A0.2,0.2 0 0 1 0.85,0.45 A0.15,0.15 0 0 1 0.85,0.75 A0.2,0.2 0 0 1 0.5,0.85 A0.2,0.2 0 0 1 0.15,0.7 A0.15,0.15 0 0 1 0.2,0.5 Z", False),  # noqa: E501
    "heart": ("M0.5,1 L0,0.4 A0.3,0.3 0 0 1 0.5,0.2 A0.3,0.3 0 0 1 1,0.4 Z", False),
    "lightningBolt": ("M0.6,0 L0.2,0.5 L0.4,0.5 L0.3,1 L0.8,0.45 L0.55,0.45 L0.7,0 Z", False),
    "sun": ("M0.5,0.3 A0.2,0.2 0 1 0 0.5,0.7 A0.2,0.2 0 1 0 0.5,0.3 Z M0.5,0 L0.5,0.15 M0.5,0.85 L0.5,1 M0,0.5 L0.15,0.5 M0.85,0.5 L1,0.5 M0.15,0.15 L0.25,0.25 M0.75,0.75 L0.85,0.85 M0.85,0.15 L0.75,0.25 M0.25,0.75 L0.15,0.85", False),  # noqa: E501
    "moon": ("M0.7,0.1 A0.4,0.4 0 1 0 0.7,0.9 A0.3,0.3 0 1 1 0.7,0.1 Z", False),
    "smileyFace": ("M0.5,0.25 A0.3,0.3 0 1 0 0.5,0.85 A0.3,0.3 0 1 0 0.5,0.25 Z M0.4,0.5 A0.04,0.04 0 1 0 0.4,0.58 A0.04,0.04 0 1 0 0.4,0.5 Z M0.6,0.5 A0.04,0.04 0 1 0 0.6,0.58 A0.04,0.04 0 1 0 0.6,0.5 Z M0.3,0.7 Q0.5,0.85 0.7,0.7", False),  # noqa: E501
    "noSmoking": ("M0.2,0.4 L0.8,0.4 L0.8,0.6 L0.2,0.6 Z M0.7,0.1 L0.7,0.3 L0.5,0.3 L0.5,0.4 M0.2,0.2 L0.8,0.8", False),
    "arc": ("M0,0.5 A0.5,0.5 0 0 1 1,0.5", True),  # path-only
    "line": ("M0,0.5 L1,0.5", True),  # we'll handle lines specially
    "straightConnector1": ("M0,0.5 L1,0.5", True),
    "bentConnector1": ("M0,0.5 L0.5,0.5 L0.5,1 L1,1", True),
    "bentConnector2": ("M0,0 L0,1 L1,1", True),
    "curvedConnector1": ("M0,0.5 Q0.5,0 1,0.5", True),
    "curvedConnector2": ("M0,0.5 Q0.5,1 1,0.5", True),
    # Power/electronics specific
    "xor": ("M0,0 L1,0 L1,1 L0,1 Z M0.15,0.15 L0.85,0.15 L0.85,0.85 L0.15,0.85 Z", False),
    "andGate": ("M0,0 L0,1 L0.4,1 A0.3,0.5 0 0 0 0.4,0 Z", False),
    "orGate": ("M0,0 L0.2,0.5 L0,1 L0.7,1 A0.3,0.5 0 0 0 0.7,0 Z", False),
    "notGate": ("M0,0 L0,1 L0.8,0.5 Z L0.8,0.4 L1,0.5 L0.8,0.6 L0.8,0.5 Z", False),
    "flowchartProcess": ("M0,0 L1,0 L1,1 L0,1 Z", False),
    "flowchartDecision": ("M0.5,0 L1,0.5 L0.5,1 L0,0.5 Z", False),
    "flowchartTerminator": ("M0,0 L1,0 A0.5,0.5 0 0 1 1,1 L0,1 A0.5,0.5 0 0 1 0,0 Z", False),
    "flowchartDocument": ("M0,0 L1,0 L1,0.85 A0.3,0.15 0 0 1 0.7,1 L0,1 Z", False),
    "flowchartPredefinedProcess": ("M0,0 L1,0 L1,1 L0,1 Z M0.1,0 L0.1,1 M0.9,0 L0.9,1", False),
    "flowchartStoredData": ("M0,0.1 L1,0 L1,0.9 L0,1 Z M0,0.1 A0.05,0.05 0 0 1 0,0.2 Z M1,0 A0.05,0.05 0 0 1 1,0.1 Z M1,0.9 A0.05,0.05 0 0 1 1,0.95 Z M0,0.95 A0.05,0.05 0 0 1 0,1 Z", False),  # noqa: E501
    "flowchartConnector": ("M0,0.5 L0.4,0.5 L0.4,1 L1,1", True),
}


if __name__ == "__main__":
    print("This is a library; use it from convert.py")
