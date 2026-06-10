"""Convert OMML (Office Math Markup Language) to MathML.

Supports the subset of OMML elements used in the source presentation:
m:r, m:t, m:e, m:sub, m:sup, m:sSub, m:sSup, m:sSubSup, m:f, m:num, m:den,
m:limUpp, m:lim, m:groupChr, m:chr, m:pos, m:nary, m:brk, m:oMath, m:oMathPara.

Output is Presentation MathML suitable for MathJax.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Optional

from lxml import etree

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

OMML_TO_MATHML = {
    "m": M_NS,
    "a": A_NS,
}

# Run classification heuristics
_OP_CHARS = set("+-−=<>≤≥≠≈±×·⋅÷∗∗∘⨂⨀∑∏∫∮∝∈∉⊂⊃∩∪∧∨¬→↔⇒⇐↦∀∃∅∇∂′″‴‰°")
_LETTER_RE = re.compile(r"^[A-Za-zА-Яа-яёЁ]$")
_DIGIT_RE = re.compile(r"^[\d.,]+$")
_WS_RE = re.compile(r"\s+")


def _is_letter(s: str) -> bool:
    return bool(_LETTER_RE.match(s))


def _is_digit(s: str) -> bool:
    return bool(_DIGIT_RE.match(s))


def _is_operator_char(s: str) -> bool:
    return all(c in _OP_CHARS for c in s) and s.strip()


def _classify_text(text: str) -> str:
    """Classify a text run as mi/mn/mo/mtext."""
    s = text.strip()
    if not s:
        return "mtext"
    if _is_digit(s):
        return "mn"
    if _is_operator_char(s):
        return "mo"
    if _is_letter(s) and len(s) == 1:
        return "mi"
    # Multi-letter: likely text or function name
    # Greek math letters U+1D400..U+1D7FF are <mi>
    if all(0x1D400 <= ord(c) <= 0x1D7FF for c in s):
        return "mi"
    return "mtext"


def _qname(prefix: str, local: str) -> str:
    return f"{{{OMML_TO_MATHML[prefix]}}}{local}"


MATH_NS_URI = "http://www.w3.org/1998/Math/MathML"

def _el(tag: str, **attrs) -> etree._Element:
    e = etree.Element("{%s}%s" % (MATH_NS_URI, tag), nsmap={None: MATH_NS_URI})
    for k, v in attrs.items():
        if v is None:
            continue
        # Allow data-* and standard MathML attrs
        e.set(k, str(v))
    return e


def convert_omml(omml_xml) -> str:
    """Convert an OMML string or element to a MathML string.

    Accepts either a string (will be parsed) or an lxml element (used directly).
    """
    if hasattr(omml_xml, "tag"):
        # It's an element - find oMath in it
        omath = None
        # If it's an oMath element directly, use it
        if etree.QName(omml_xml).localname == "oMath":
            omath = omml_xml
        else:
            # Search descendants for oMath
            for el in omml_xml.iter():
                if etree.QName(el).localname == "oMath":
                    omath = el
                    break
        if omath is None:
            return ""
        MATH_NS = "http://www.w3.org/1998/Math/MathML"
        math = etree.Element("{%s}math" % MATH_NS, nsmap={None: MATH_NS})
        math.set("display", "block")
        convert_math_elem(omath, math)
        return etree.tostring(math, encoding="unicode")

    # Wrap in a root with namespaces declared so XPath can find m:* elements
    wrapped = (
        '<root xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        + omml_xml
        + "</root>"
    )
    try:
        root = etree.fromstring(wrapped.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        return f'<math><merror>{escape_xml(str(e))}</merror></math>'

    # Find first oMath element
    omath = root.find(".//{%s}oMath" % M_NS)
    if omath is None:
        # Look for oMathPara > oMath
        ompara = root.find(".//{%s}oMathPara" % M_NS)
        if ompara is not None:
            omath = ompara.find("{%s}oMath" % M_NS)
    if omath is None:
        return ""

    # Build <math> element
    math = _el("math")
    math.set("display", "block")
    convert_math_elem(omath, math)
    return etree.tostring(math, encoding="unicode")


def escape_xml(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def convert_math_elem(elem, parent):
    """Convert a single OMML element to MathML and append to parent."""
    tag = etree.QName(elem).localname
    if tag == "r":
        # math run
        rpr = elem.find("{%s}rPr" % M_NS)
        style = None
        if rpr is not None:
            sty = []
            if rpr.get("i") in ("1", "true"):
                sty.append("font-style:italic")
            if rpr.get("b") in ("1", "true"):
                sty.append("font-weight:bold")
            sz = rpr.get("sz")
            if sz:
                sty.append(f"font-size:{int(sz)/100:.0f}pt")
            if sty:
                style = ";".join(sty)
        # get all text content
        text = "".join((t.text or "") for t in elem.findall("{%s}t" % M_NS))
        if not text:
            return
        cls = _classify_text(text)
        m = _el(cls)
        m.text = text
        if style:
            m.set("style", style)
        parent.append(m)
    elif tag == "sSub":
        e = elem.find("{%s}e" % M_NS)
        sub = elem.find("{%s}sub" % M_NS)
        if e is None or sub is None:
            return
        node = _el("msub")
        convert_math_elem(e, node)
        convert_math_elem(sub, node)
        parent.append(node)
    elif tag == "sSup":
        e = elem.find("{%s}e" % M_NS)
        sup = elem.find("{%s}sup" % M_NS)
        if e is None or sup is None:
            return
        node = _el("msup")
        convert_math_elem(e, node)
        convert_math_elem(sup, node)
        parent.append(node)
    elif tag == "sSubSup":
        e = elem.find("{%s}e" % M_NS)
        sub = elem.find("{%s}sub" % M_NS)
        sup = elem.find("{%s}sup" % M_NS)
        if e is None:
            return
        node = _el("msubsup")
        convert_math_elem(e, node)
        if sub is not None:
            convert_math_elem(sub, node)
        if sup is not None:
            convert_math_elem(sup, node)
        parent.append(node)
    elif tag == "f":
        num = elem.find("{%s}num" % M_NS)
        den = elem.find("{%s}den" % M_NS)
        if num is None or den is None:
            return
        node = _el("mfrac")
        convert_math_elem(num, node)
        convert_math_elem(den, node)
        parent.append(node)
    elif tag == "rad":
        e = elem.find("{%s}e" % M_NS)
        deg = elem.find("{%s}deg" % M_NS)
        if e is None:
            return
        node = _el("msqrt")
        if deg is not None:
            node.tag = "mroot"
            convert_math_elem(deg, node)
        convert_math_elem(e, node)
        parent.append(node)
    elif tag == "limUpp":
        e = elem.find("{%s}e" % M_NS)
        lim = elem.find("{%s}lim" % M_NS)
        if e is None:
            return
        node = _el("munder")
        convert_math_elem(e, node)
        if lim is not None:
            convert_math_elem(lim, node)
        parent.append(node)
    elif tag == "limLow":
        e = elem.find("{%s}e" % M_NS)
        lim = elem.find("{%s}lim" % M_NS)
        if e is None:
            return
        node = _el("mover")
        convert_math_elem(e, node)
        if lim is not None:
            convert_math_elem(lim, node)
        parent.append(node)
    elif tag == "groupChr":
        e = elem.find("{%s}e" % M_NS)
        chr_el = elem.find("{%s}chr" % M_NS)
        if e is None:
            return
        node = _el("mover")
        convert_math_elem(e, node)
        if chr_el is not None and chr_el.get("{%s}val" % M_NS):
            ch = chr_el.get("{%s}val" % M_NS)
            ch_node = _el("mo", stretchy="true")
            ch_node.text = ch
            node.append(ch_node)
        parent.append(node)
    elif tag == "nary":
        e = elem.find("{%s}e" % M_NS)
        sub = elem.find("{%s}sub" % M_NS)
        sup = elem.find("{%s}sup" % M_NS)
        chr_el = elem.find("{%s}chr" % M_NS)
        if e is None:
            return
        op_char = chr_el.get("{%s}val" % M_NS) if chr_el is not None else "∑"
        node = _el("munderover")
        op = _el("mo", stretchy="true")
        op.text = op_char
        node.append(op)
        if sub is not None:
            convert_math_elem(sub, node)
        else:
            node.append(_el("mrow"))
        if sup is not None:
            convert_math_elem(sup, node)
        else:
            node.append(_el("mrow"))
        convert_math_elem(e, node)
        parent.append(node)
    elif tag == "brk":
        parent.append(_el("mspace", linebreak="newline"))
    elif tag == "oMath":
        # Convert children directly. If 0 children, skip.
        if len(elem) == 0:
            return
        if len(elem) == 1:
            convert_math_elem(elem[0], parent)
        else:
            mrow = _el("mrow")
            for ch in elem:
                convert_math_elem(ch, mrow)
            parent.append(mrow)
    elif tag == "oMathPara":
        # mrow of all oMath children
        for ch in elem:
            convert_math_elem(ch, parent)
    elif tag in ("e", "sub", "sup", "num", "den", "lim", "deg"):
        # Container - convert children into a new mrow
        if len(elem) == 0:
            return
        if len(elem) == 1:
            # Single child: convert it directly
            convert_math_elem(elem[0], parent)
            return
        # Multiple children: wrap in mrow
        mrow = _el("mrow")
        for ch in elem:
            convert_math_elem(ch, mrow)
        parent.append(mrow)
    elif tag in ("rPr", "sSubPr", "sSupPr", "sSubSupPr", "fPr", "radPr",
                 "limUppPr", "limLowPr", "groupChrPr", "naryPr",
                 "oMathParaPr", "jc", "chr", "pos", "vertJc", "ctrlPr", "degHide",
                 "begChr", "endChr", "type", "prr"):
        # Property elements - skip
        pass
    else:
        # Unknown - try to recurse into children
        for ch in elem:
            convert_math_elem(ch, parent)


def _convert_children(elem, parent):
    """Convert all children of elem into parent."""
    for ch in elem:
        convert_math_elem(ch, parent)


def extract_math_from_paragraph(p_elem) -> list[dict]:
    """Extract math/text blocks from an <a:p> element in document order.

    Returns a list of dicts:
        {"type": "math", "omml": "<m:oMath>...</m:oMath>"}
        {"type": "text", "runs": [<a:r>...], "pPr": <a:pPr>}

    For paragraphs that have no math at all, returns [{"type": "text", "runs": [...], "pPr": ...}].
    """
    ns = {"a": A_NS, "m": M_NS}
    blocks = []
    current_text_runs = []
    current_pPr = p_elem.find("a:pPr", ns)
    for ch in p_elem:
        local = etree.QName(ch).localname
        if local == "oMath":
            if current_text_runs:
                blocks.append({"type": "text", "runs": current_text_runs, "pPr": current_pPr})
                current_text_runs = []
            omml = etree.tostring(ch, encoding="unicode")
            blocks.append({"type": "math", "omml": omml})
        elif local == "r":
            current_text_runs.append(ch)
        elif local == "endParaRPr":
            pass
        # other elements: skip
    if current_text_runs:
        blocks.append({"type": "text", "runs": current_text_runs, "pPr": current_pPr})
    if not blocks:
        blocks = [{"type": "text", "runs": [], "pPr": current_pPr}]
    return blocks


def has_math(p_elem) -> bool:
    ns = {"a": A_NS, "m": M_NS}
    return p_elem.find(".//{%s}oMath" % M_NS) is not None
