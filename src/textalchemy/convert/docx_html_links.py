"""Stable Word bookmark names for arbitrary HTML fragment identifiers."""

from hashlib import sha256


def bookmark_name(identifier):
    return "html_" + sha256(identifier.encode("utf-8")).hexdigest()[:32]


def add_bookmark(paragraph, identifier):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    existing = paragraph.part.element.findall(".//" + qn("w:bookmarkStart"))
    number = max([int(node.get(qn("w:id"), "0")) for node in existing] + [0]) + 1
    start, end = OxmlElement("w:bookmarkStart"), OxmlElement("w:bookmarkEnd")
    start.set(qn("w:id"), str(number))
    start.set(qn("w:name"), bookmark_name(identifier))
    end.set(qn("w:id"), str(number))
    paragraph._p.append(start)
    paragraph._p.append(end)
