"""Экспорт богатой промежуточной модели в самодостаточный HTML."""

from __future__ import annotations

import base64
import re
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import (
    Block,
    Box,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    Paragraph,
    Resource,
    Section,
    Table,
    TextRun,
    TextStyle,
)

_MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML"
_MATHML_ELEMENTS = {
    "annotation",
    "maction",
    "math",
    "menclose",
    "merror",
    "mfenced",
    "mfrac",
    "mi",
    "mmultiscripts",
    "mn",
    "mo",
    "mover",
    "mpadded",
    "mphantom",
    "mprescripts",
    "mroot",
    "mrow",
    "ms",
    "mspace",
    "msqrt",
    "mstyle",
    "msub",
    "msubsup",
    "msup",
    "mtable",
    "mtd",
    "mtext",
    "mtr",
    "munder",
    "munderover",
    "none",
    "semantics",
}
_COLOR_RE = re.compile(r"^(?:#[0-9a-fA-F]{3,8}|[a-zA-Z]{1,24})$")
_MEDIA_TYPE_RE = re.compile(r"^image/[a-zA-Z0-9.+-]+$")
_HEADING_RE = re.compile(r"^(?:heading|заголовок)\s*([1-6])$", re.IGNORECASE)


def write_html_model(document: DocumentModel, output_path: str | Path) -> ConversionReport:
    """Записать ``DocumentModel`` в один переносимый HTML-файл."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = ConversionReport(output)
    renderer = _HtmlRenderer(document, report)
    body = renderer.render()
    title = escape(str(document.metadata.get("title") or "Document"))
    language = escape(str(document.metadata.get("language") or "ru"), quote=True)
    html = (
        "<!doctype html>\n"
        f'<html lang="{language}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n<style>\n{renderer.stylesheet()}\n</style>\n"
        f"</head>\n<body>\n{body}\n</body>\n</html>\n"
    )
    try:
        output.write_text(html, encoding="utf-8")
    except OSError as error:
        report.add(IssueSeverity.ERROR, "html-write", str(error))
        return report
    report.metrics.update(renderer.metrics)
    report.metrics["sections"] = len(document.sections or [Section()])
    report.metrics["resources"] = len(document.resources)
    report.metrics["embedded_resources"] = len(renderer.embedded_resources)
    return report


class _HtmlRenderer:
    def __init__(self, document: DocumentModel, report: ConversionReport):
        self.document = document
        self.report = report
        self.metrics = {"paragraphs": 0, "tables": 0, "images": 0, "formulas": 0}
        self.embedded_resources: set[str] = set()

    def stylesheet(self, *, include_page_rules: bool = True) -> str:
        pages = []
        for index, section in enumerate(self.document.sections or [Section()]):
            page = section.page
            pages.append(
                f"@page ta-page-{index} {{ size: {page.width.pt:g}pt {page.height.pt:g}pt; "
                f"margin: {page.margin_top.pt:g}pt {page.margin_right.pt:g}pt "
                f"{page.margin_bottom.pt:g}pt {page.margin_left.pt:g}pt; }}"
            )
            pages.append(
                f".ta-section-{index} {{ page: ta-page-{index}; width: {page.width.pt:g}pt; "
                f"min-height: {page.height.pt:g}pt; padding: {page.margin_top.pt:g}pt {page.margin_right.pt:g}pt "
                f"{page.margin_bottom.pt:g}pt {page.margin_left.pt:g}pt; }}"
            )
        rules = [
            "* { box-sizing: border-box; }",
            "html { background: #e5e7eb; }",
            "body { margin: 0; color: #111827; font-family: Arial, sans-serif; }",
            ".ta-section { position: relative; display: flex; flex-direction: column; margin: 16pt auto; "
            "background: white; overflow: hidden; box-shadow: 0 2pt 12pt #0002; }",
            ".ta-main { position: relative; flex: 1; }",
            ".ta-header, .ta-footer { position: relative; color: #4b5563; }",
            ".ta-header { margin-bottom: 12pt; }",
            ".ta-footer { margin-top: 12pt; }",
            "p { margin: 0 0 8pt; white-space: pre-wrap; }",
            "table { width: 100%; border-collapse: collapse; margin: 0 0 8pt; }",
            "td, th { border: .75pt solid #9ca3af; padding: 4pt; vertical-align: top; }",
            "img { max-width: 100%; height: auto; vertical-align: middle; }",
            ".ta-formula { font-family: 'Cambria Math', 'STIX Two Math', serif; white-space: pre-wrap; }",
            ".ta-formula-display { display: block; margin: 8pt 0; text-align: center; }",
        ]
        if include_page_rules:
            rules.extend(
                [
                    "@media print { html { background: white; } body { margin: 0; } .ta-section { margin: 0; "
                    "box-shadow: none; break-after: page; overflow: visible; } "
                    ".ta-section:last-child { break-after: auto; } }",
                    *pages,
                ]
            )
        return "\n".join(rules)

    def render(self) -> str:
        sections = self.document.sections or [Section()]
        return "\n".join(self._section(section, index) for index, section in enumerate(sections))

    def _section(self, section: Section, index: int) -> str:
        if _has_content(section.headers) or _has_content(section.footers):
            self.report.add(
                IssueSeverity.LOSS,
                "running-header-footer",
                "HTML displays headers and footers once per section; repetition on overflow pages is not guaranteed",
                f"sections[{index}]",
            )
        header = self._blocks(section.headers, f"sections[{index}].headers")
        main = self._blocks(section.blocks, f"sections[{index}].blocks")
        footer = self._blocks(section.footers, f"sections[{index}].footers")
        return (
            f'<section class="ta-section ta-section-{index}">'
            f'<header class="ta-header">{header}</header>'
            f'<main class="ta-main">{main}</main>'
            f'<footer class="ta-footer">{footer}</footer>'
            "</section>"
        )

    def _blocks(self, blocks: list[Block], location: str) -> str:
        return "".join(self._block(block, f"{location}[{index}]") for index, block in enumerate(blocks))

    def _block(self, block: Block, location: str) -> str:
        if isinstance(block, Paragraph):
            return self._paragraph(block, location)
        if isinstance(block, Table):
            return self._table(block, location)
        if isinstance(block, Formula):
            self.metrics["formulas"] += 1
            return self._formula(block, location, block_level=True)
        if isinstance(block, Image):
            self.metrics["images"] += 1
            return self._image(block, location, block_level=True)
        return ""

    def _paragraph(self, paragraph: Paragraph, location: str) -> str:
        self.metrics["paragraphs"] += 1
        style_name = str(paragraph.properties.get("style_name") or paragraph.style_id or "")
        match = _HEADING_RE.match(style_name.replace("_", " "))
        tag = f"h{match.group(1)}" if match else "p"
        styles = self._box_style(paragraph.box, positioned=True)
        if paragraph.alignment in {"left", "right", "center", "justify"}:
            styles.append(f"text-align:{paragraph.alignment}")
        property_map = {
            "left_indent_pt": "margin-left",
            "right_indent_pt": "margin-right",
            "first_line_indent_pt": "text-indent",
            "space_before_pt": "margin-top",
            "space_after_pt": "margin-bottom",
        }
        for source, target in property_map.items():
            value = paragraph.properties.get(source)
            if isinstance(value, (int, float)):
                styles.append(f"{target}:{value:g}pt")
        line_spacing = paragraph.properties.get("line_spacing")
        if isinstance(line_spacing, (int, float)):
            styles.append(f"line-height:{line_spacing:g}")
        content = "".join(self._inline(item, f"{location}.content[{index}]") for index, item in enumerate(paragraph.content))
        return f"<{tag}{_style_attribute(styles)}>{content}</{tag}>"

    def _inline(self, item: TextRun | Formula | Image, location: str) -> str:
        if isinstance(item, TextRun):
            return self._run(item, location)
        if isinstance(item, Formula):
            self.metrics["formulas"] += 1
            return self._formula(item, location, block_level=False)
        self.metrics["images"] += 1
        return self._image(item, location, block_level=False)

    def _run(self, run: TextRun, location: str) -> str:
        content = escape(run.text)
        styles = self._text_style(run.style)
        attributes = _style_attribute(styles)
        if run.style.language:
            attributes += f' lang="{escape(run.style.language, quote=True)}"'
        if run.link:
            href = _safe_link(run.link)
            if href is None:
                self.report.add(IssueSeverity.LOSS, "hyperlink", "unsafe hyperlink scheme was removed", location)
            else:
                return f'<a href="{escape(href, quote=True)}"{attributes}>{content}</a>'
        return f"<span{attributes}>{content}</span>" if attributes else content

    def _formula(self, formula: Formula, location: str, *, block_level: bool) -> str:
        classes = "ta-formula ta-formula-display" if formula.display or block_level else "ta-formula"
        if formula.format is FormulaFormat.MATHML:
            try:
                mathml = _safe_mathml(formula.value)
                return f'<span class="{classes}">{mathml}</span>'
            except ValueError as error:
                self.report.add(IssueSeverity.LOSS, "formula", f"invalid MathML replaced by fallback: {error}", location)
        else:
            self.report.add(
                IssueSeverity.LOSS,
                "formula",
                f"{formula.format.value} has no native self-contained HTML renderer; fallback text used",
                location,
            )
        fallback = escape(formula.fallback_text or formula.value)
        return (
            f'<span class="{classes}" data-formula-format="{formula.format.value}" '
            f'data-formula-source="{escape(formula.value, quote=True)}">{fallback}</span>'
        )

    def _image(self, image: Image, location: str, *, block_level: bool) -> str:
        resource = self.document.resources.get(image.resource_id)
        if resource is None:
            self.report.add(IssueSeverity.ERROR, "image", f"resource {image.resource_id!r} not found", location)
            return escape(image.alt_text or f"[{image.resource_id}]")
        try:
            uri = self._resource_uri(resource)
        except (OSError, ValueError) as error:
            self.report.add(IssueSeverity.ERROR, "image", str(error), location)
            return escape(image.alt_text or f"[{resource.filename or resource.id}]")
        self.embedded_resources.add(resource.id)
        styles = self._box_style(image.box, positioned=block_level)
        tag = (
            f'<img src="{uri}" alt="{escape(image.alt_text, quote=True)}"'
            f'{_style_attribute(styles)} loading="eager">'
        )
        return f'<div class="ta-image">{tag}</div>' if block_level else tag

    def _resource_uri(self, resource: Resource) -> str:
        if not _MEDIA_TYPE_RE.fullmatch(resource.media_type):
            raise ValueError(f"resource {resource.id!r} is not an image ({resource.media_type})")
        if resource.data is not None:
            raw = resource.data
        elif resource.source is not None:
            raw = Path(resource.source).read_bytes()
        else:
            raise ValueError(f"resource {resource.id!r} has no content")
        encoded = base64.b64encode(raw).decode("ascii")
        return f"data:{resource.media_type};base64,{encoded}"

    def _table(self, table: Table, location: str) -> str:
        self.metrics["tables"] += 1
        rows = []
        for row_index, row in enumerate(table.rows):
            cells = []
            for cell_index, cell in enumerate(row.cells):
                attributes = ""
                if cell.row_span > 1:
                    attributes += f' rowspan="{cell.row_span}"'
                if cell.column_span > 1:
                    attributes += f' colspan="{cell.column_span}"'
                content = self._blocks(cell.blocks, f"{location}.rows[{row_index}].cells[{cell_index}].blocks")
                cells.append(f"<td{attributes}>{content}</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return f'<table{_style_attribute(self._box_style(table.box, positioned=True))}><tbody>{"".join(rows)}</tbody></table>'

    @staticmethod
    def _text_style(style: TextStyle) -> list[str]:
        values: list[str] = []
        if style.font_family:
            values.append(f'font-family:"{_css_string(style.font_family)}"')
        if style.font_size:
            values.append(f"font-size:{style.font_size.pt:g}pt")
        if style.bold is True:
            values.append("font-weight:700")
        if style.italic is True:
            values.append("font-style:italic")
        if style.underline is True:
            values.append("text-decoration:underline")
        if style.superscript is True:
            values.extend(("vertical-align:super", "font-size:smaller"))
        elif style.subscript is True:
            values.extend(("vertical-align:sub", "font-size:smaller"))
        if style.color and _COLOR_RE.match(style.color):
            values.append(f"color:{style.color}")
        if style.background and _COLOR_RE.match(style.background):
            values.append(f"background-color:{style.background}")
        return values

    @staticmethod
    def _box_style(box: Box | None, *, positioned: bool) -> list[str]:
        if box is None:
            return []
        values: list[str] = []
        if box.width > 0:
            values.append(f"width:{box.width:g}pt")
        if box.height > 0:
            values.append(f"height:{box.height:g}pt")
        if positioned and (box.x or box.y):
            values.extend(("position:absolute", f"left:{box.x:g}pt", f"top:{box.y:g}pt"))
        if box.rotation:
            values.append(f"transform:rotate({box.rotation:g}deg)")
            values.append("transform-origin:center")
        return values


def _style_attribute(styles: list[str]) -> str:
    if not styles:
        return ""
    return f' style="{escape(";".join(styles), quote=True)}"'


def _css_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")


def _safe_link(value: str) -> str | None:
    scheme = urlsplit(value).scheme.lower()
    return value if scheme in {"", "http", "https", "mailto", "tel", "ftp"} else None


def _has_content(blocks: list[Block]) -> bool:
    for block in blocks:
        if isinstance(block, Paragraph) and block.content:
            return True
        if isinstance(block, Table) and block.rows:
            return True
        if isinstance(block, (Formula, Image)):
            return True
    return False


def _safe_mathml(value: str) -> str:
    from lxml import etree

    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        root = etree.fromstring(value.encode("utf-8"), parser)
    except (etree.XMLSyntaxError, ValueError) as error:
        raise ValueError(str(error)) from error
    for element in root.iter():
        name = etree.QName(element)
        if name.namespace not in {None, _MATHML_NAMESPACE}:
            raise ValueError(f"foreign element {name.localname!r} is not allowed")
        if name.localname not in _MATHML_ELEMENTS:
            raise ValueError(f"MathML element {name.localname!r} is not allowed")
        if element is root and name.localname != "math":
            raise ValueError("root element must be math")
        for attribute in list(element.attrib):
            local_name = etree.QName(attribute).localname.lower()
            if local_name.startswith("on") or local_name in {"href", "src", "style"}:
                del element.attrib[attribute]
    return etree.tostring(root, encoding="unicode")


__all__ = ["write_html_model"]
