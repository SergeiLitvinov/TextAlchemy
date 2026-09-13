"""Native Word numbering for independently editable HTML lists."""


def apply_html_list(paragraph, properties):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    part = paragraph.part.numbering_part
    cache = getattr(part, "_textalchemy_html_lists", None)
    if cache is None:
        cache = part._textalchemy_html_lists = {}
    key = properties["html_list_id"]
    root = part.element
    if key not in cache:
        abstract_id = max([int(n.get(qn("w:abstractNumId"))) for n in root.findall(qn("w:abstractNum"))] + [-1]) + 1
        abstract = OxmlElement("w:abstractNum")
        abstract.set(qn("w:abstractNumId"), str(abstract_id))
        level = OxmlElement("w:lvl")
        level.set(qn("w:ilvl"), "0")
        ordered = properties.get("list_kind") == "ordered"
        for tag, value in (
            ("start", properties.get("list_start", 1)),
            ("numFmt", "decimal" if ordered else "bullet"),
            ("lvlText", "%1." if ordered else "•"),
        ):
            node = OxmlElement("w:" + tag)
            node.set(qn("w:val"), str(value))
            level.append(node)
        abstract.append(level)
        root.insert(0, abstract)
        cache[key] = root.add_num(abstract_id).numId
    props = paragraph._p.get_or_add_pPr()
    number = props.get_or_add_numPr()
    number.get_or_add_ilvl().val = 0
    number.get_or_add_numId().val = cache[key]
    from docx.shared import Pt

    paragraph.paragraph_format.left_indent = Pt(18 * (int(properties.get("list_level", 0)) + 1))
    paragraph.paragraph_format.first_line_indent = Pt(-12)
