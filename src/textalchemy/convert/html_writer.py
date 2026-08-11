"""Экспорт богатой промежуточной модели в самодостаточный HTML."""

from __future__ import annotations

import base64
import math
import re
from html import escape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit

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

_PRESET_GEOMETRY_CACHE: dict[str, tuple[str, bool]] | None = None


def _preset_geometry() -> dict[str, tuple[str, bool]]:
    """Ленивый импорт справочника автофигур (не тянет python-pptx при импорте)."""
    global _PRESET_GEOMETRY_CACHE
    if _PRESET_GEOMETRY_CACHE is None:
        from textalchemy.convert.pptx_to_html._pptx_lib import PRST_GEOMETRY  # type: ignore[import-not-found]

        _PRESET_GEOMETRY_CACHE = PRST_GEOMETRY
    return _PRESET_GEOMETRY_CACHE


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
_PT_TO_PX = 96.0 / 72.0


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
        from textalchemy.core.io import atomic_write_text

        atomic_write_text(output, html, encoding="utf-8")
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
        section_styles: list[str] = []
        background = section.properties.get("background_fill")
        if isinstance(background, str) and _COLOR_RE.match(background):
            section_styles.append(f"background-color:{background}")
        return (
            f'<section class="ta-section ta-section-{index}"{_style_attribute(section_styles)}>'
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
        pptx_props = paragraph.properties.get("pptx")
        styles = self._geometry_style(paragraph.box, paragraph.properties, positioned=True)
        shape = pptx_props.get("shape") if isinstance(pptx_props, dict) else None
        chart = pptx_props.get("chart") if isinstance(pptx_props, dict) else None
        if isinstance(shape, dict) and paragraph.box is not None:
            if not (paragraph.box.x or paragraph.box.y):
                styles.extend(("position:absolute", "left:0pt", "top:0pt"))
            uri = _shape_svg_uri(shape)
            if uri is not None:
                styles.append(f'background-image:url("{uri}")')
                styles.append("background-size:100% 100%")
                styles.append("background-repeat:no-repeat")
            else:
                self._report_missing_shape(shape, location)
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
        chart_svg = _chart_svg(chart) if isinstance(chart, dict) else None
        if isinstance(chart, dict) and chart_svg is None:
            self.report.add(
                IssueSeverity.LOSS,
                "chart",
                f"chart type {chart.get('chart_type')!r} is represented as text",
                location,
            )
        content = chart_svg or "".join(
            self._inline(item, f"{location}.content[{index}]") for index, item in enumerate(paragraph.content)
        )
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
        if formula.format in (FormulaFormat.MATHML, FormulaFormat.OMML):
            try:
                mathml = _safe_mathml(_formula_to_mathml(formula))
                return f'<span class="{classes}">{mathml}</span>'
            except ValueError as error:
                self.report.add(IssueSeverity.LOSS, "formula", f"invalid formula replaced by fallback: {error}", location)
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
        styles = self._geometry_style(image.box, image.properties, positioned=block_level)
        tag = f'<img src="{uri}" alt="{escape(image.alt_text, quote=True)}"{_style_attribute(styles)} loading="eager">'
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
        styles = self._geometry_style(table.box, table.properties, positioned=True)
        return f"<table{_style_attribute(styles)}><tbody>{''.join(rows)}</tbody></table>"

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

    @staticmethod
    def _geometry_style(box: Box | None, properties: Any, *, positioned: bool) -> list[str]:
        affine = _pptx_affine(properties) if positioned else None
        if affine is None:
            return _HtmlRenderer._box_style(box, positioned=positioned)
        matrix, width, height = affine
        a, b, c, d, e, f = matrix
        return [
            f"width:{width:g}pt",
            f"height:{height:g}pt",
            "position:absolute",
            "left:0pt",
            "top:0pt",
            f"transform:matrix({a:g},{b:g},{c:g},{d:g},{e:g},{f:g})",
            "transform-origin:0 0",
        ]

    def _report_missing_shape(self, shape: dict[str, Any], location: str) -> None:
        prst = shape.get("prst")
        if prst and prst not in _preset_geometry():
            self.report.add(IssueSeverity.LOSS, "preset-shape", f"preset shape {prst!r} is not rendered", location)
        elif shape.get("fill") == "blip":
            self.report.add(IssueSeverity.LOSS, "shape-fill", "blipFill shape background is not rendered", location)


def _style_attribute(styles: list[str]) -> str:
    if not styles:
        return ""
    return f' style="{escape(";".join(styles), quote=True)}"'


def _pptx_affine(properties: Any) -> tuple[list[float], float, float] | None:
    if not hasattr(properties, "get"):
        return None
    pptx = properties.get("pptx")
    transform = pptx.get("transform") if isinstance(pptx, dict) else None
    if not isinstance(transform, dict):
        return None
    matrix = transform.get("matrix")
    width = transform.get("width_pt")
    height = transform.get("height_pt")
    if not isinstance(matrix, list) or len(matrix) != 6:
        return None
    values = [float(value) for value in matrix if isinstance(value, (int, float))]
    if len(values) != 6 or not all(math.isfinite(value) for value in values):
        return None
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)) or width <= 0 or height <= 0:
        return None
    return values, float(width), float(height)


_CHART_COLORS = ("#4472C4", "#ED7D31", "#A5A5A5", "#FFC000", "#5B9BD5", "#70AD47")


def _shade_hex(color: str, factor: float) -> str:
    """Осветлить (``factor > 0``) или затемнить (``factor < 0``) hex-цвет для 3D-граней."""
    match = re.match(r"#([0-9a-fA-F]{6})", color)
    if not match:
        return color
    value = int(match.group(1), 16)
    red, green, blue = (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF
    if factor >= 0:
        red = int(red + (255 - red) * factor)
        green = int(green + (255 - green) * factor)
        blue = int(blue + (255 - blue) * factor)
    else:
        factor = -factor
        red = int(red * (1 - factor))
        green = int(green * (1 - factor))
        blue = int(blue * (1 - factor))
    return f"#{red:02X}{green:02X}{blue:02X}"


def _chart_3d_scene(chart: dict[str, Any]) -> dict[str, Any] | None:
    """Build a deterministic perspective projection from OOXML ``view3D``."""
    if not chart.get("chart_3d"):
        return None
    view = chart.get("view3d") or {}
    depth_percent = float(view.get("depth_percent") or 150.0)
    depth = max(6.0, min(36.0, 18.0 * depth_percent / 150.0))
    rot_x = max(-90.0, min(90.0, float(view.get("rot_x") or 15.0)))
    rot_y = float(view.get("rot_y") or 20.0) % 360.0
    perspective = max(0.0, min(240.0, float(view.get("perspective") or 30.0)))
    perspective_scale = 1.0 + perspective / 480.0
    dx = depth * math.sin(math.radians(rot_y)) * perspective_scale
    dy = -depth * math.sin(math.radians(rot_x)) * perspective_scale
    # A zero rotation still needs visible depth for right-angle-axes views.
    if abs(dx) < 1.0:
        dx = depth * 0.35
    if abs(dy) < 1.0:
        dy = -depth * 0.22
    return {
        "depth": depth,
        "dx": dx,
        "dy": dy,
        "shape": str(chart.get("chart_3d_shape") or "box"),
        "side_wall": chart.get("side_wall") or {},
        "back_wall": chart.get("back_wall") or {},
        "floor": chart.get("floor") or {},
    }


def _chart_3d_walls(left: float, top: float, width: float, height: float, scene: dict[str, Any] | None) -> list[str]:
    """Render back/side/floor planes before the chart data."""
    if scene is None:
        return []
    dx, dy = scene["dx"], scene["dy"]
    right, bottom = left + width, top + height
    back_fill = scene["back_wall"].get("fill", "#F3F4F6")
    side_fill = scene["side_wall"].get("fill", "#E5E7EB")
    floor_fill = scene["floor"].get("fill", "#F9FAFB")
    return [
        f'<path class="chart-3d-back-wall" d="M {left + dx:g} {top + dy:g} H {right + dx:g} '
        f'V {bottom + dy:g} H {left + dx:g} Z" fill="{back_fill}" stroke="#D1D5DB"/>',
        f'<path class="chart-3d-side-wall" d="M {right:g} {top:g} L {right + dx:g} {top + dy:g} '
        f'L {right + dx:g} {bottom + dy:g} L {right:g} {bottom:g} Z" fill="{side_fill}" stroke="#D1D5DB"/>',
        f'<path class="chart-3d-floor" d="M {left:g} {bottom:g} L {right:g} {bottom:g} '
        f'L {right + dx:g} {bottom + dy:g} L {left + dx:g} {bottom + dy:g} Z" '
        f'fill="{floor_fill}" stroke="#D1D5DB"/>',
    ]


def _bar_3d_faces(
    x: float,
    y: float,
    width: float,
    height: float,
    color: str,
    scene: dict[str, Any] | None,
) -> list[str]:
    """Render projected side/top faces using the configured view rotation."""
    if scene is None or height <= 1.0:
        return []
    dx, dy = scene["dx"], scene["dy"]
    return [
        f'<path d="M {x + width:g} {y:g} L {x + width + dx:g} {y + dy:g} '
        f'L {x + width + dx:g} {y + dy + height:g} L {x + width:g} {y + height:g} Z" '
        f'fill="{_shade_hex(color, -0.35)}"/>',
        f'<path d="M {x:g} {y:g} L {x + dx:g} {y + dy:g} L {x + width + dx:g} {y + dy:g} '
        f'L {x + width:g} {y:g} Z" fill="{_shade_hex(color, 0.35)}"/>',
    ]


def _bar_mark_svg(
    x: float,
    y: float,
    width: float,
    height: float,
    color: str,
    title: str,
    scene: dict[str, Any] | None,
) -> list[str]:
    """Render a box/cylinder/cone/pyramid data mark as editable SVG."""
    shape = scene["shape"].lower() if scene is not None else "box"
    safe_title = escape(title)
    if shape in {"cylinder", "cyl"} and scene is not None:
        cap = min(width * 0.28, 7.0)
        return [
            f'<path d="M {x:g} {y:g} V {y + height:g} A {width / 2:g} {cap:g} 0 0 0 {x + width:g} '
            f'{y + height:g} V {y:g} Z" fill="{color}"><title>{safe_title}</title></path>',
            f'<ellipse cx="{x + width / 2:g}" cy="{y:g}" rx="{width / 2:g}" ry="{cap:g}" fill="{_shade_hex(color, 0.3)}"/>',
            f'<ellipse cx="{x + width / 2 + scene["dx"]:g}" cy="{y + scene["dy"]:g}" '
            f'rx="{width / 2:g}" ry="{cap:g}" fill="{_shade_hex(color, -0.3)}" opacity="0.7"/>',
        ]
    if shape in {"cone", "pyramid"} and scene is not None:
        center = x + width / 2
        back_center = center + scene["dx"]
        back_y = y + scene["dy"]
        return [
            f'<path d="M {back_center:g} {back_y:g} L {x + scene["dx"]:g} {y + height + scene["dy"]:g} '
            f'L {x + width + scene["dx"]:g} {y + height + scene["dy"]:g} Z" '
            f'fill="{_shade_hex(color, -0.35)}"/>',
            f'<path d="M {center:g} {y:g} L {x:g} {y + height:g} L {x + width:g} {y + height:g} Z" '
            f'fill="{color}"><title>{safe_title}</title></path>',
            f'<path d="M {center:g} {y:g} L {back_center:g} {back_y:g} '
            f'L {x + width + scene["dx"]:g} {y + height + scene["dy"]:g} L {x + width:g} {y + height:g} Z" '
            f'fill="{_shade_hex(color, -0.2)}"/>',
        ]
    return [
        f'<rect x="{x:g}" y="{y:g}" width="{width:g}" height="{height:g}" fill="{color}"><title>{safe_title}</title></rect>',
        *_bar_3d_faces(x, y, width, height, color, scene),
    ]


def _chart_svg(chart: dict[str, Any]) -> str | None:
    chart_type = chart.get("chart_type")
    categories = [str(value) for value in chart.get("categories") or []]
    series = _numeric_chart_series(chart.get("series"))
    if not series:
        return None
    if not categories:
        categories = [str(index + 1) for index in range(max(len(item["values"]) for item in series))]
    axes = chart.get("axes") or {}
    value_axis = axes.get("value") or {}
    label_style = {
        "chart": chart.get("data_labels") or {},
        "formatter": _number_formatter(chart.get("data_labels", {}).get("num_format")),
    }
    secondary_series = [item for item in series if item.get("axis") == "secondary_value"]
    if secondary_series:
        primary_series = [item for item in series if item.get("axis") != "secondary_value"]
        if primary_series:
            primary_style = _chart_axis_style(primary_series, value_axis)
            primary_style["gap_width"] = chart.get("gap_width", 150.0)
            primary_style["overlap"] = chart.get("overlap", 0.0)
            secondary_style = _chart_axis_style(secondary_series, axes.get("secondary_value") or {})
            secondary_style["gap_width"] = chart.get("gap_width", 150.0)
            secondary_style["overlap"] = chart.get("overlap", 0.0)
            body = _dual_axis_chart_svg(
                categories,
                primary_series,
                secondary_series,
                chart=chart,
                axis_style=primary_style,
                secondary_style=secondary_style,
                label_style=label_style,
            )
        else:
            body = None
    else:
        grouping = chart.get("grouping")
        axis_style = _chart_axis_style(series, value_axis)
        axis_style["gap_width"] = chart.get("gap_width", 150.0)
        axis_style["overlap"] = chart.get("overlap", 0.0)
        three_d = _chart_3d_scene(chart)
        if chart_type == "barChart" and grouping in {None, "clustered", "standard", "stacked", "percentStacked"}:
            horizontal = chart.get("bar_direction") == "bar"
            combo_kinds = _chart_combo_kinds(series)
            if combo_kinds:
                body = _combo_chart_svg(categories, series, kinds=combo_kinds, axis_style=axis_style, label_style=label_style)
            elif grouping in {"stacked", "percentStacked"}:
                body = _stacked_bar_chart_svg(
                    categories,
                    series,
                    horizontal=horizontal,
                    percent=grouping == "percentStacked",
                    axis_style=axis_style,
                    label_style=label_style,
                    depth=three_d,
                )
            else:
                body = _bar_chart_svg(
                    categories, series, horizontal=horizontal, axis_style=axis_style, label_style=label_style, depth=three_d
                )
        elif chart_type == "lineChart" and grouping in {None, "standard"}:
            body = _line_chart_svg(categories, series, axis_style=axis_style, label_style=label_style, scene=three_d)
        elif chart_type in {"pieChart", "doughnutChart"}:
            body = _pie_chart_svg(
                categories,
                series[0],
                doughnut=chart_type == "doughnutChart",
                show_legend=bool(chart.get("legend", True)),
                label_style=label_style,
                tilt=max(0.45, 1.0 - abs(three_d["dy"]) / 80.0) if three_d else 1.0,
                scene=three_d,
            )
        else:
            body = None
    if body is None:
        return None
    title = str(chart.get("title") or "Chart")
    description = _chart_description(categories, series)
    return (
        f'<svg class="ta-chart" viewBox="0 0 800 450" width="100%" height="100%" role="img" '
        f'aria-label="{escape(title, quote=True)}" xmlns="http://www.w3.org/2000/svg">'
        f"<title>{escape(title)}</title><desc>{escape(description)}</desc>"
        f'<rect width="800" height="450" fill="white"/>'
        f'<text x="400" y="28" text-anchor="middle" font-family="Arial" font-size="20" font-weight="700">'
        f"{escape(title)}</text>{body}{_chart_decorations(chart, series)}</svg>"
    )


def _chart_axis_style(series: list[dict[str, Any]], value_axis: dict[str, Any]) -> dict[str, Any]:
    """Собрать параметры отрисовки осей: диапазон, шаг, формат, видимость меток."""
    minimum, maximum = _chart_range(series)
    if not value_axis.get("auto_min") and isinstance(value_axis.get("min"), (int, float)):
        minimum = float(value_axis["min"])
    if not value_axis.get("auto_max") and isinstance(value_axis.get("max"), (int, float)):
        maximum = float(value_axis["max"])
    if math.isclose(minimum, maximum):
        maximum = minimum + 1.0
    hidden = bool(value_axis.get("hidden"))
    show_labels = not hidden and value_axis.get("tick_label_position") != "none"
    formatter = _number_formatter(value_axis.get("num_format"))
    return {
        "minimum": minimum,
        "maximum": maximum,
        "major_unit": value_axis.get("major_unit"),
        "formatter": formatter,
        "show_labels": show_labels,
    }


def _number_formatter(num_format: Any) -> Callable[[float], str]:
    """Построить функцию форматирования значения по Excel-коду формата ``numFmt``."""
    if not isinstance(num_format, str) or not num_format or num_format.strip() == "General":
        return _format_chart_general
    percent = "%" in num_format
    decimal_match = re.search(r"0\.(0+)", num_format)
    decimals = len(decimal_match.group(1)) if decimal_match else 0
    comma = "," in num_format

    def fmt(value: float) -> str:
        if percent:
            scaled = value * 100.0
            text = f"{scaled:.{decimals}f}%"
            return text
        if comma:
            return f"{value:,.{decimals}f}"
        return f"{value:.{decimals}f}"

    return fmt


def _format_chart_general(value: float) -> str:
    return f"{value:g}"


def _series_label_context(item: dict[str, Any], chart_labels: dict[str, Any]) -> tuple[dict[str, Any], Callable[[float], str]]:
    """Слить настройки подписей серии с общими и вернуть (labels, formatter)."""
    labels = dict(chart_labels)
    labels.update(item.get("data_labels") or {})
    return labels, _number_formatter(labels.get("num_format"))


def _data_label_text(
    item: dict[str, Any],
    value: float,
    *,
    percent: float | None,
    category: str | None,
    labels: dict[str, Any],
    formatter: Callable[[float], str],
) -> str:
    """Собрать текст подписи данных по флагам ``c:dLbls``."""
    parts = []
    if labels.get("show_series"):
        parts.append(item["name"])
    if labels.get("show_category") and category:
        parts.append(category)
    if labels.get("show_percent") and percent is not None:
        parts.append(f"{percent:.1f}%")
    elif labels.get("show_value"):
        parts.append(formatter(value))
    if not parts:
        return ""
    return str(labels.get("separator") or ", ").join(parts)


def _numeric_chart_series(raw_series: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_series, list):
        return []
    result = []
    for index, item in enumerate(raw_series):
        if not isinstance(item, dict):
            continue
        values = []
        for value in item.get("values") or []:
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = 0.0
            values.append(number if math.isfinite(number) else 0.0)
        if values:
            color = item.get("color")
            safe_color = color if isinstance(color, str) and _COLOR_RE.match(color) else _CHART_COLORS[index % len(_CHART_COLORS)]
            result.append(
                {
                    "name": str(item.get("name") or f"Series {index + 1}"),
                    "values": values,
                    "color": safe_color,
                    "chart_type": item.get("chart_type"),
                    "axis": item.get("axis"),
                    "data_points": item.get("data_points") if isinstance(item.get("data_points"), dict) else None,
                    "trendline": item.get("trendline") if isinstance(item.get("trendline"), dict) else None,
                    "error_bars": item.get("error_bars") if isinstance(item.get("error_bars"), dict) else None,
                }
            )
    return result


def _bar_chart_svg(
    categories: list[str],
    series: list[dict[str, Any]],
    *,
    horizontal: bool,
    axis_style: dict[str, Any],
    label_style: dict[str, Any],
    depth: dict[str, Any] | None = None,
) -> str:
    if horizontal:
        return _horizontal_bar_chart_svg(categories, series, axis_style=axis_style, label_style=label_style, scene=depth)
    left, top, width, height = 65.0, 55.0, 650.0, 320.0
    minimum, maximum = axis_style["minimum"], axis_style["maximum"]
    parts = _chart_3d_walls(left, top, width, height, depth)
    parts.extend(_chart_grid(left, top, width, height, minimum, maximum, axis_style))
    parts.extend(
        _bar_series_parts(
            categories,
            series,
            left=left,
            top=top,
            width=width,
            height=height,
            axis_style=axis_style,
            label_style=label_style,
            depth=depth,
        )
    )
    for category_index, category in enumerate(categories):
        parts.append(_svg_label(left + (category_index + 0.5) * width / max(len(categories), 1), 397, category, anchor="middle"))
    return "".join(parts)


def _bar_series_parts(
    categories: list[str],
    series: list[dict[str, Any]],
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    axis_style: dict[str, Any],
    label_style: dict[str, Any],
    depth: dict[str, Any] | None = None,
) -> list[str]:
    """������� ������ �����, ������������������ �� ``axis_style`` (��� ����� � ����� ���������)."""
    minimum, maximum = axis_style["minimum"], axis_style["maximum"]
    baseline = top + height * maximum / (maximum - minimum)
    category_width = width / max(len(categories), 1)
    series_count = max(len(series), 1)
    gap_width = axis_style.get("gap_width", 150.0) / 100.0
    overlap = axis_style.get("overlap", 0.0) / 100.0
    bar_width = category_width / (series_count + gap_width)
    bar_step = bar_width * (1.0 - overlap)
    cluster_width = (series_count - 1) * bar_step + bar_width
    chart_labels = label_style["chart"]
    parts = []
    for category_index, category in enumerate(categories):
        group_x = left + category_index * category_width + (category_width - cluster_width) / 2
        for series_index, item in enumerate(series):
            value = item["values"][category_index] if category_index < len(item["values"]) else 0.0
            value_y = top + height * (maximum - value) / (maximum - minimum)
            y = min(value_y, baseline)
            bar_height = max(abs(baseline - value_y), 0.75)
            x = group_x + series_index * bar_step
            if depth is not None and series_count > 1:
                series_depth = series_index / (series_count - 1)
                x += depth["dx"] * series_depth
                y += depth["dy"] * series_depth
                value_y += depth["dy"] * series_depth
            color = _point_color(item, category_index)
            parts.extend(_bar_mark_svg(x, y, bar_width, bar_height, color, f"{item['name']}: {value:g}", depth))
            _append_bar_label(parts, item, value, None, category, x + bar_width / 2, y, chart_labels, anchor="middle")
            parts.extend(
                _error_bar_parts(
                    item,
                    category_index,
                    value,
                    x + bar_width / 2,
                    value_y,
                    minimum=minimum,
                    maximum=maximum,
                    top=top,
                    height=height,
                )
            )
    return parts


def _horizontal_bar_chart_svg(
    categories: list[str],
    series: list[dict[str, Any]],
    *,
    axis_style: dict[str, Any],
    label_style: dict[str, Any],
    scene: dict[str, Any] | None = None,
) -> str:
    left, top, width, height = 120.0, 55.0, 595.0, 320.0
    minimum, maximum = axis_style["minimum"], axis_style["maximum"]
    baseline = left + width * (-minimum) / (maximum - minimum)
    parts = _chart_3d_walls(left, top, width, height, scene)
    parts.append(f'<line x1="{baseline:g}" y1="{top:g}" x2="{baseline:g}" y2="{top + height:g}" stroke="#6B7280"/>')
    parts.extend(
        _horizontal_bar_series_parts(
            categories,
            series,
            left=left,
            top=top,
            width=width,
            height=height,
            axis_style=axis_style,
            label_style=label_style,
            scene=scene,
        )
    )
    for category_index, category in enumerate(categories):
        label_y = top + (category_index + 0.5) * height / max(len(categories), 1)
        parts.append(_svg_label(left - 8, label_y, category, anchor="end"))
    return "".join(parts)


def _horizontal_bar_series_parts(
    categories: list[str],
    series: list[dict[str, Any]],
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    axis_style: dict[str, Any],
    label_style: dict[str, Any],
    scene: dict[str, Any] | None = None,
) -> list[str]:
    """Горизонтальные столбцы серий, отмасштабированных по ``axis_style``."""
    minimum, maximum = axis_style["minimum"], axis_style["maximum"]
    baseline = left + width * (-minimum) / (maximum - minimum)
    category_height = height / max(len(categories), 1)
    series_count = max(len(series), 1)
    gap_width = axis_style.get("gap_width", 150.0) / 100.0
    overlap = axis_style.get("overlap", 0.0) / 100.0
    bar_height = category_height / (series_count + gap_width)
    bar_step = bar_height * (1.0 - overlap)
    cluster_height = (series_count - 1) * bar_step + bar_height
    chart_labels = label_style["chart"]
    parts = []
    for category_index, category in enumerate(categories):
        group_y = top + category_index * category_height + (category_height - cluster_height) / 2
        for series_index, item in enumerate(series):
            value = item["values"][category_index] if category_index < len(item["values"]) else 0.0
            value_x = left + width * (value - minimum) / (maximum - minimum)
            x = min(value_x, baseline)
            bar_width = max(abs(value_x - baseline), 0.75)
            y = group_y + series_index * bar_step
            if scene is not None and series_count > 1:
                series_depth = series_index / (series_count - 1)
                x += scene["dx"] * series_depth
                y += scene["dy"] * series_depth
                value_x += scene["dx"] * series_depth
            color = _point_color(item, category_index)
            parts.append(
                f'<rect x="{x:g}" y="{y:g}" width="{bar_width:g}" height="{bar_height:g}" '
                f'fill="{color}">'
                f"<title>{escape(item['name'])}: {value:g}</title></rect>"
            )
            parts.extend(_bar_3d_faces(x, y, bar_width, bar_height, color, scene))
            if value >= 0:
                label_x, anchor = value_x + 4, "start"
            else:
                label_x, anchor = value_x - 4, "end"
            _append_bar_label(parts, item, value, None, category, label_x, y + bar_height * 0.45, chart_labels, anchor=anchor)
            parts.extend(
                _error_bar_parts(
                    item,
                    category_index,
                    value,
                    value_x,
                    y + bar_height / 2,
                    minimum=minimum,
                    maximum=maximum,
                    top=top,
                    height=height,
                    direction="x",
                )
            )
    return parts


def _append_bar_label(
    parts: list[str],
    item: dict[str, Any],
    value: float,
    percent: float | None,
    category: str,
    x: float,
    y: float,
    chart_labels: dict[str, Any],
    *,
    anchor: str,
) -> None:
    labels, formatter = _series_label_context(item, chart_labels)
    if not (labels.get("show_value") or labels.get("show_percent") or labels.get("show_category") or labels.get("show_series")):
        return
    text = _data_label_text(item, value, percent=percent, category=category, labels=labels, formatter=formatter)
    if text:
        parts.append(_svg_label(x, y - 4, text, anchor=anchor))


def _line_chart_svg(
    categories: list[str],
    series: list[dict[str, Any]],
    *,
    axis_style: dict[str, Any],
    label_style: dict[str, Any],
    scene: dict[str, Any] | None = None,
) -> str:
    left, top, width, height = 65.0, 55.0, 650.0, 320.0
    minimum, maximum = axis_style["minimum"], axis_style["maximum"]
    parts = _chart_3d_walls(left, top, width, height, scene)
    parts.extend(_chart_grid(left, top, width, height, minimum, maximum, axis_style))
    parts.extend(
        _line_series_parts(
            categories,
            series,
            left=left,
            top=top,
            width=width,
            height=height,
            axis_style=axis_style,
            label_style=label_style,
            scene=scene,
        )
    )
    denominator = max(len(categories) - 1, 1)
    for index, category in enumerate(categories):
        parts.append(_svg_label(left + width * index / denominator, 397, category, anchor="middle"))
    return "".join(parts)


def _line_series_parts(
    categories: list[str],
    series: list[dict[str, Any]],
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    axis_style: dict[str, Any],
    label_style: dict[str, Any],
    scene: dict[str, Any] | None = None,
) -> list[str]:
    """Линии и точки серий с трендами и планками погрешностей (без сетки)."""
    minimum, maximum = axis_style["minimum"], axis_style["maximum"]
    denominator = max(len(categories) - 1, 1)
    chart_labels = label_style["chart"]
    parts = []
    for series_index, item in enumerate(series):
        series_parts: list[str] = []
        points = []
        circles = []
        for index, value in enumerate(item["values"][: len(categories)]):
            x = left + width * index / denominator
            y = top + height * (maximum - value) / (maximum - minimum)
            points.append(f"{x:g},{y:g}")
            circles.append(
                f'<circle cx="{x:g}" cy="{y:g}" r="4" fill="{_point_color(item, index)}">'
                f"<title>{escape(item['name'])}: {value:g}</title></circle>"
            )
            _append_bar_label(series_parts, item, value, None, categories[index], x, y, chart_labels, anchor="middle")
            series_parts.extend(
                _error_bar_parts(item, index, value, x, y, minimum=minimum, maximum=maximum, top=top, height=height)
            )
        series_parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{item["color"]}" stroke-width="3"/>')
        series_parts.extend(circles)
        series_parts.extend(
            _trendline_parts(item, categories, left=left, top=top, width=width, height=height, axis_style=axis_style)
        )
        if scene is not None and len(series) > 1:
            fraction = series_index / (len(series) - 1)
            parts.append(
                f'<g class="chart-3d-series" transform="translate({scene["dx"] * fraction:g} '
                f'{scene["dy"] * fraction:g})">{"".join(series_parts)}</g>'
            )
        else:
            parts.extend(series_parts)
    return parts


def _chart_combo_kinds(series: list[dict[str, Any]]) -> set[str]:
    """Вернуть множество типов серий в комбинированной диаграмме."""
    kinds = {item.get("chart_type") for item in series if item.get("chart_type")}
    if not kinds or not kinds.issubset({"barChart", "lineChart"}):
        return set()
    return kinds


def _combo_chart_svg(
    categories: list[str],
    series: list[dict[str, Any]],
    *,
    kinds: set[str],
    axis_style: dict[str, Any],
    label_style: dict[str, Any],
) -> str:
    """Совместить столбцы (barChart) и линии (lineChart) на общих осях."""
    left, top, width, height = 65.0, 55.0, 650.0, 320.0
    bar_items = [item for item in series if item.get("chart_type") in {None, "barChart"}]
    line_items = [item for item in series if item.get("chart_type") == "lineChart"]
    parts = _chart_grid(left, top, width, height, axis_style["minimum"], axis_style["maximum"], axis_style)
    if bar_items:
        parts.extend(
            _bar_series_parts(
                categories,
                bar_items,
                left=left,
                top=top,
                width=width,
                height=height,
                axis_style=axis_style,
                label_style=label_style,
            )
        )
    if line_items:
        parts.extend(
            _line_series_parts(
                categories,
                line_items,
                left=left,
                top=top,
                width=width,
                height=height,
                axis_style=axis_style,
                label_style=label_style,
            )
        )
    for index, category in enumerate(categories):
        parts.append(_svg_label(left + (index + 0.5) * width / max(len(categories), 1), 397, category, anchor="middle"))
    return "".join(parts)


def _dual_axis_chart_svg(
    categories: list[str],
    primary_series: list[dict[str, Any]],
    secondary_series: list[dict[str, Any]],
    *,
    chart: dict[str, Any],
    axis_style: dict[str, Any],
    secondary_style: dict[str, Any],
    label_style: dict[str, Any],
) -> str:
    """Совместить серии двух осей значений (левая/правая) в одном поле построения."""
    left, top, width, height = 65.0, 55.0, 620.0, 320.0
    horizontal = chart.get("bar_direction") == "bar"
    parts = _chart_grid(left, top, width, height, axis_style["minimum"], axis_style["maximum"], axis_style)
    parts.extend(_chart_grid_right(left, top, width, height, secondary_style))
    parts.extend(
        _dual_axis_series(
            categories,
            primary_series,
            left=left,
            top=top,
            width=width,
            height=height,
            axis_style=axis_style,
            label_style=label_style,
            horizontal=horizontal,
        )
    )
    parts.extend(
        _dual_axis_series(
            categories,
            secondary_series,
            left=left,
            top=top,
            width=width,
            height=height,
            axis_style=secondary_style,
            label_style=label_style,
            horizontal=horizontal,
        )
    )
    for index, category in enumerate(categories):
        parts.append(_svg_label(left + (index + 0.5) * width / max(len(categories), 1), 397, category, anchor="middle"))
    return "".join(parts)


def _dual_axis_series(
    categories: list[str],
    series: list[dict[str, Any]],
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    axis_style: dict[str, Any],
    label_style: dict[str, Any],
    horizontal: bool,
) -> list[str]:
    """Отрисовать группу серий одной оси: столбцами или линиями по типу серий."""
    kinds = _chart_combo_kinds(series)
    if kinds and "lineChart" in kinds:
        return _line_series_parts(
            categories, series, left=left, top=top, width=width, height=height, axis_style=axis_style, label_style=label_style
        )
    if horizontal:
        return _horizontal_bar_series_parts(
            categories, series, left=left, top=top, width=width, height=height, axis_style=axis_style, label_style=label_style
        )
    return _bar_series_parts(
        categories, series, left=left, top=top, width=width, height=height, axis_style=axis_style, label_style=label_style
    )


def _pie_chart_svg(
    categories: list[str],
    series: dict[str, Any],
    *,
    doughnut: bool,
    show_legend: bool,
    label_style: dict[str, Any],
    tilt: float = 1.0,
    scene: dict[str, Any] | None = None,
) -> str:
    values = [max(value, 0.0) for value in series["values"][: len(categories)]]
    total = sum(values)
    if total <= 0:
        return _svg_label(400, 220, "No positive data", anchor="middle")
    center_x, center_y, radius = 310.0, 225.0, 145.0
    if scene is not None:
        center_x += scene["dx"] * 0.12
    radius_y = radius * tilt
    hole_radius_y = 72.0 * tilt
    extrusion = min(24.0, max(4.0, abs(scene["dy"]) * 0.75)) if scene is not None else 0.0
    angle = -math.pi / 2
    parts = []
    bottom_parts = []
    labels, formatter = _series_label_context(series, label_style["chart"])
    for index, (category, value) in enumerate(zip(categories, values, strict=False)):
        sweep = 2 * math.pi * value / total
        end = angle + sweep
        x1, y1 = center_x + radius * math.cos(angle), center_y + radius_y * math.sin(angle)
        x2, y2 = center_x + radius * math.cos(end), center_y + radius_y * math.sin(end)
        large = 1 if sweep > math.pi else 0
        color = _point_color(series, index) or _CHART_COLORS[index % len(_CHART_COLORS)]
        path = f"M {center_x:g} {center_y:g} L {x1:g} {y1:g} A {radius:g} {radius_y:g} 0 {large} 1 {x2:g} {y2:g} Z"
        if extrusion:
            bottom_path = (
                f"M {center_x:g} {center_y + extrusion:g} L {x1:g} {y1 + extrusion:g} "
                f"A {radius:g} {radius_y:g} 0 {large} 1 {x2:g} {y2 + extrusion:g} Z"
            )
            bottom_parts.append(f'<path class="chart-3d-pie-depth" d="{bottom_path}" fill="{_shade_hex(color, -0.35)}"/>')
        parts.append(f'<path d="{path}" fill="{color}" stroke="white"><title>{escape(category)}: {value:g}</title></path>')
        percent = 100.0 * value / total if total else 0.0
        text = _data_label_text(series, value, percent=percent, category=category, labels=labels, formatter=formatter)
        if text:
            mid = angle + sweep / 2
            position = labels.get("position")
            if position == "ctr":
                label_radius, fill = radius * 0.62, "white"
            elif position == "inEnd":
                label_radius, fill = radius * 0.82, "white"
            else:
                label_radius, fill = radius + 20, None
            label_x = center_x + label_radius * math.cos(mid)
            label_y = center_y + label_radius * tilt * math.sin(mid)
            parts.append(_svg_label(label_x, label_y + 4, text, anchor="middle", fill=fill))
        if show_legend:
            parts.append(f'<rect x="500" y="{85 + index * 26:g}" width="14" height="14" fill="{color}"/>')
            parts.append(_svg_label(522, 97 + index * 26, category, anchor="start"))
        angle = end
    if doughnut:
        parts.append(f'<ellipse cx="{center_x:g}" cy="{center_y:g}" rx="72" ry="{hole_radius_y:g}" fill="white"/>')
    return "".join(bottom_parts + parts)


def _stacked_bar_chart_svg(
    categories: list[str],
    series: list[dict[str, Any]],
    *,
    horizontal: bool,
    percent: bool,
    axis_style: dict[str, Any],
    label_style: dict[str, Any],
    depth: dict[str, Any] | None = None,
) -> str:
    values, minimum, maximum = _stacked_values(categories, series, percent=percent)
    if percent:
        minimum = axis_style["minimum"]
        maximum = axis_style["maximum"]
    if horizontal:
        return _horizontal_stacked_bars(
            categories,
            series,
            values,
            minimum,
            maximum,
            percent=percent,
            axis_style=axis_style,
            label_style=label_style,
            scene=depth,
        )
    left, top, width, height = 65.0, 55.0, 650.0, 320.0
    category_width = width / max(len(categories), 1)
    gap_width = axis_style.get("gap_width", 150.0) / 100.0
    bar_width = category_width / (1.0 + gap_width)
    parts = _chart_3d_walls(left, top, width, height, depth)
    parts.extend(_chart_grid(left, top, width, height, minimum, maximum, axis_style))
    chart_labels = label_style["chart"]
    for category_index, category in enumerate(categories):
        positive = 0.0
        negative = 0.0
        x = left + (category_index + 0.5) * category_width - bar_width / 2
        for series_index, item in enumerate(series):
            value = values[series_index][category_index]
            start = positive if value >= 0 else negative
            end = start + value
            if value >= 0:
                positive = end
            else:
                negative = end
            start_y = top + height * (maximum - start) / (maximum - minimum)
            end_y = top + height * (maximum - end) / (maximum - minimum)
            y = min(start_y, end_y)
            segment_height = max(abs(start_y - end_y), 0.75)
            original = _series_value(item, category_index)
            color = item["color"]
            parts.extend(_bar_mark_svg(x, y, bar_width, segment_height, color, f"{item['name']}: {original:g}", depth))
            total_value = _stack_total(values, category_index, value)
            segment_percent = 100.0 * value / total_value if total_value else 0.0
            percent_label = segment_percent if percent or segment_percent != 0.0 else None
            _append_bar_label(parts, item, original, percent_label, category, x + bar_width / 2, y, chart_labels, anchor="middle")
        parts.append(_svg_label(left + (category_index + 0.5) * category_width, 397, category, anchor="middle"))
    return "".join(parts)


def _stack_total(values: list[list[float]], category_index: int, value: float) -> float:
    return sum(row[category_index] for row in values)


def _horizontal_stacked_bars(
    categories: list[str],
    series: list[dict[str, Any]],
    values: list[list[float]],
    minimum: float,
    maximum: float,
    *,
    percent: bool,
    axis_style: dict[str, Any],
    label_style: dict[str, Any],
    scene: dict[str, Any] | None = None,
) -> str:
    left, top, width, height = 120.0, 55.0, 595.0, 320.0
    category_height = height / max(len(categories), 1)
    gap_width = axis_style.get("gap_width", 150.0) / 100.0
    bar_height = category_height / (1.0 + gap_width)
    baseline = left + width * (-minimum) / (maximum - minimum)
    parts = _chart_3d_walls(left, top, width, height, scene)
    parts.append(f'<line x1="{baseline:g}" y1="{top:g}" x2="{baseline:g}" y2="{top + height:g}" stroke="#6B7280"/>')
    chart_labels = label_style["chart"]
    for category_index, category in enumerate(categories):
        positive = 0.0
        negative = 0.0
        y = top + (category_index + 0.5) * category_height - bar_height / 2
        parts.append(_svg_label(left - 8, top + (category_index + 0.55) * category_height, category, anchor="end"))
        for series_index, item in enumerate(series):
            value = values[series_index][category_index]
            start = positive if value >= 0 else negative
            end = start + value
            if value >= 0:
                positive = end
            else:
                negative = end
            start_x = left + width * (start - minimum) / (maximum - minimum)
            end_x = left + width * (end - minimum) / (maximum - minimum)
            x = min(start_x, end_x)
            segment_width = max(abs(start_x - end_x), 0.75)
            original = _series_value(item, category_index)
            parts.append(
                f'<rect x="{x:g}" y="{y:g}" width="{segment_width:g}" height="{bar_height:g}" '
                f'fill="{item["color"]}"><title>{escape(item["name"])}: {original:g}</title></rect>'
            )
            parts.extend(_bar_3d_faces(x, y, segment_width, bar_height, item["color"], scene))
            total_value = _stack_total(values, category_index, value)
            segment_percent = 100.0 * value / total_value if total_value else 0.0
            percent_label = segment_percent if percent or segment_percent != 0.0 else None
            if value >= 0:
                label_x, anchor = end_x + 4, "start"
            else:
                label_x, anchor = end_x - 4, "end"
            _append_bar_label(
                parts, item, original, percent_label, category, label_x, y + bar_height * 0.45, chart_labels, anchor=anchor
            )
    return "".join(parts)


def _stacked_values(
    categories: list[str],
    series: list[dict[str, Any]],
    *,
    percent: bool,
) -> tuple[list[list[float]], float, float]:
    values = [[_series_value(item, index) for index in range(len(categories))] for item in series]
    if percent:
        for category_index in range(len(categories)):
            positive_total = sum(max(row[category_index], 0.0) for row in values) or 1.0
            negative_total = sum(abs(min(row[category_index], 0.0)) for row in values) or 1.0
            for row in values:
                value = row[category_index]
                row[category_index] = 100.0 * value / (positive_total if value >= 0 else negative_total)
    positive_stacks = [sum(max(row[index], 0.0) for row in values) for index in range(len(categories))]
    negative_stacks = [sum(min(row[index], 0.0) for row in values) for index in range(len(categories))]
    minimum = min(0.0, min(negative_stacks, default=0.0))
    maximum = max(0.0, max(positive_stacks, default=0.0))
    if math.isclose(minimum, maximum):
        maximum = minimum + 1.0
    return values, minimum, maximum


def _series_value(series: dict[str, Any], index: int) -> float:
    values = series["values"]
    return values[index] if index < len(values) else 0.0


def _point_color(item: dict[str, Any], index: int) -> str:
    """Цвет отдельной точки данных (``c:dPt``) либо цвет серии."""
    points = item.get("data_points")
    if isinstance(points, dict):
        point = points.get(index)
        if isinstance(point, dict):
            color = point.get("color")
            if isinstance(color, str) and _COLOR_RE.match(color):
                return color
    return item["color"]


def _error_bar_parts(
    item: dict[str, Any],
    index: int,
    value: float,
    x: float,
    y: float,
    *,
    minimum: float,
    maximum: float,
    top: float,
    height: float,
    direction: str = "y",
) -> list[str]:
    """Планки погрешностей точки данных (``c:errBars``) в виде линий с колпачками."""
    error = item.get("error_bars")
    if not isinstance(error, dict):
        return []
    plus, minus = _error_bar_offsets(item, error, index, value)
    if plus is None and minus is None:
        return []
    span = maximum - minimum
    if span == 0:
        return []
    color = error.get("color") or item["color"]
    parts: list[str] = []
    if direction == "x":
        x_plus = x - height * plus / span if plus is not None else x
        x_minus = x + height * minus / span if minus is not None else x
        parts.append(
            f'<line x1="{min(x_plus, x_minus):g}" y1="{y:g}" x2="{max(x_plus, x_minus):g}" y2="{y:g}" '
            f'stroke="{color}" stroke-width="1.5"/>'
        )
        for end_x in (x_plus, x_minus):
            parts.append(
                f'<line x1="{end_x:g}" y1="{y - 6:g}" x2="{end_x:g}" y2="{y + 6:g}" stroke="{color}" stroke-width="1.5"/>'
            )
    else:
        y_plus = y - height * plus / span if plus is not None else y
        y_minus = y + height * minus / span if minus is not None else y
        parts.append(f'<line x1="{x:g}" y1="{y_plus:g}" x2="{x:g}" y2="{y_minus:g}" stroke="{color}" stroke-width="1.5"/>')
        for end_y in (y_plus, y_minus):
            parts.append(
                f'<line x1="{x - 6:g}" y1="{end_y:g}" x2="{x + 6:g}" y2="{end_y:g}" stroke="{color}" stroke-width="1.5"/>'
            )
    return parts


def _error_bar_offsets(
    item: dict[str, Any], error: dict[str, Any], index: int, value: float
) -> tuple[float | None, float | None]:
    """Величины (plus, minus) планок погрешности в единицах оси по типу ``c:errValType``."""
    value_type = error.get("value_type")
    if value_type == "fixedVal":
        amount = float(error.get("value", 0.0) or 0.0)
        return amount, amount
    if value_type == "percentage":
        percent = float(error.get("value", 0.0) or 0.0)
        amount = abs(value) * percent / 100.0
        return amount, amount
    if value_type == "stdDev":
        deviation = _standard_deviation(item["values"])
        return deviation, deviation
    if value_type == "stdErr":
        deviation = _standard_deviation(item["values"]) / math.sqrt(max(len(item["values"]), 1))
        return deviation, deviation
    if value_type == "cust":
        return _error_series_value(error.get("plus"), index), _error_series_value(error.get("minus"), index)
    if value_type == "val":
        amount = _error_series_value(error.get("y_val"), index)
        return amount, amount
    return None, None


def _error_series_value(raw: Any, index: int) -> float | None:
    """Значение планки из числовой серии (``c:yVal``/``c:plus``/``c:minus``)."""
    if not isinstance(raw, list):
        return None
    try:
        values = [float(item) for item in raw]
    except (TypeError, ValueError):
        return None
    if index < len(values):
        return values[index]
    return None


def _standard_deviation(values: list[float]) -> float:
    """Выборочное стандартное отклонение по всей серии."""
    numbers = [float(v) for v in values if isinstance(v, (int, float))]
    if not numbers:
        return 0.0
    mean = sum(numbers) / len(numbers)
    variance = sum((value - mean) ** 2 for value in numbers) / len(numbers)
    return math.sqrt(variance)


def _trendline_parts(
    item: dict[str, Any],
    categories: list[str],
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    axis_style: dict[str, Any],
) -> list[str]:
    """Линия тренда серии (``c:trendline``): linear, movingAvg, exp или poly."""
    trend = item.get("trendline")
    if not isinstance(trend, dict):
        return []
    points = item["values"][: len(categories)]
    if len(points) < 2:
        return []
    trend_type = trend.get("type") or "linear"
    color = trend.get("color") or item["color"]
    minimum, maximum = axis_style["minimum"], axis_style["maximum"]
    denominator = max(len(categories) - 1, 1)
    dash_style = f'fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="6 4"'
    if trend_type == "movingAvg":
        period = max(int(trend.get("period", 2) or 2), 1)
        averages = []
        for index in range(len(points)):
            window = points[max(0, index - period + 1) : index + 1]
            averages.append(sum(window) / len(window))
        coordinates = []
        for index, average in enumerate(averages):
            x = left + width * index / denominator
            y = top + height * (maximum - average) / (maximum - minimum)
            coordinates.append(f"{x:g},{y:g}")
        return [f'<polyline points="{" ".join(coordinates)}" {dash_style}/>']
    if trend_type == "exp":
        log_x = [index for index, point in enumerate(points) if point > 0]
        log_points = [math.log(points[index]) for index in log_x]
        if len(log_x) < 2:
            return []
        slope, intercept = _least_squares(log_x, log_points)
        y0 = math.exp(intercept)
        y1 = math.exp(intercept + slope * (len(points) - 1))
        y0_px = top + height * (maximum - y0) / (maximum - minimum)
        y1_px = top + height * (maximum - y1) / (maximum - minimum)
        return [f'<line x1="{left:g}" y1="{y0_px:g}" x2="{left + width:g}" y2="{y1_px:g}" {dash_style}/>']
    if trend_type == "poly":
        order = min(max(int(trend.get("order", 2) or 2), 1), 6)
        coefficients = _polyfit(list(range(len(points))), list(points), order)
        if coefficients is None:
            return []
        coordinates = []
        for index in range(len(points)):
            y_value = sum(c * index**degree for degree, c in enumerate(coefficients))
            x = left + width * index / denominator
            y = top + height * (maximum - y_value) / (maximum - minimum)
            coordinates.append(f"{x:g},{y:g}")
        return [f'<polyline points="{" ".join(coordinates)}" {dash_style}/>']
    slope, intercept = _least_squares(list(range(len(points))), list(points))
    y0 = intercept
    y1 = intercept + slope * (len(points) - 1)
    y0_px = top + height * (maximum - y0) / (maximum - minimum)
    y1_px = top + height * (maximum - y1) / (maximum - minimum)
    return [f'<line x1="{left:g}" y1="{y0_px:g}" x2="{left + width:g}" y2="{y1_px:g}" {dash_style}/>']


def _least_squares(x: list[float], y: list[float]) -> tuple[float, float]:
    """Метод наименьших квадратов: (наклон, свободный член) прямой ``y = kx + b``."""
    count = len(x)
    if count == 0:
        return 0.0, 0.0
    sx = sum(x)
    sy = sum(y)
    sxx = sum(xi * xi for xi in x)
    sxy = sum(xi * yi for xi, yi in zip(x, y, strict=False))
    denominator = count * sxx - sx * sx
    if math.isclose(denominator, 0.0):
        return 0.0, sy / count
    slope = (count * sxy - sx * sy) / denominator
    intercept = (sy - slope * sx) / count
    return slope, intercept


def _polyfit(x: list[float], y: list[float], order: int) -> list[float] | None:
    """Полиномиальная регрессия через нормальные уравнения с методом Гаусса."""
    degree = order + 1
    if len(x) < degree:
        return None
    matrix = [[0.0] * (degree + 1) for _ in range(degree)]
    for row in range(degree):
        for col in range(degree):
            matrix[row][col] = sum(xi ** (row + col) for xi in x)
        matrix[row][degree] = sum(yi * xi**row for xi, yi in zip(x, y, strict=False))
    for col in range(degree):
        pivot = max(range(col, degree), key=lambda row: abs(matrix[row][col]))
        if pivot != col:
            matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        if abs(matrix[col][col]) < 1e-12:
            return None
        for row in range(degree):
            if row == col:
                continue
            factor = matrix[row][col] / matrix[col][col]
            for col_index in range(col, degree + 1):
                matrix[row][col_index] -= factor * matrix[col][col_index]
    return [matrix[k][degree] / matrix[k][k] for k in range(degree)]


def _chart_range(series: list[dict[str, Any]]) -> tuple[float, float]:
    values = [value for item in series for value in item["values"]]
    minimum = min(0.0, min(values, default=0.0))
    maximum = max(0.0, max(values, default=0.0))
    if math.isclose(minimum, maximum):
        maximum = minimum + 1.0
    return minimum, maximum


def _chart_grid(
    left: float,
    top: float,
    width: float,
    height: float,
    minimum: float,
    maximum: float,
    axis_style: dict[str, Any] | None = None,
) -> list[str]:
    axis_style = axis_style or {}
    formatter = axis_style.get("formatter") or _format_chart_general
    show_labels = bool(axis_style.get("show_labels", True))
    parts = []
    for value in _axis_steps(minimum, maximum, axis_style.get("major_unit")):
        fraction = (maximum - value) / (maximum - minimum)
        y = top + height * fraction
        parts.append(f'<line x1="{left:g}" y1="{y:g}" x2="{left + width:g}" y2="{y:g}" stroke="#D1D5DB"/>')
        if show_labels:
            parts.append(_svg_label(left - 8, y + 4, formatter(value), anchor="end"))
    return parts


def _chart_grid_right(
    left: float,
    top: float,
    width: float,
    height: float,
    axis_style: dict[str, Any] | None = None,
) -> list[str]:
    """Вторичная сетка с метками справа (для диаграмм с двумя осями значений)."""
    axis_style = axis_style or {}
    formatter = axis_style.get("formatter") or _format_chart_general
    show_labels = bool(axis_style.get("show_labels", True))
    minimum, maximum = axis_style["minimum"], axis_style["maximum"]
    parts = []
    for value in _axis_steps(minimum, maximum, axis_style.get("major_unit")):
        fraction = (maximum - value) / (maximum - minimum)
        y = top + height * fraction
        parts.append(f'<line x1="{left:g}" y1="{y:g}" x2="{left + width:g}" y2="{y:g}" stroke="#E5E7EB" stroke-dasharray="2 2"/>')
        if show_labels:
            parts.append(_svg_label(left + width + 8, y + 4, formatter(value), anchor="start"))
    return parts


def _axis_steps(minimum: float, maximum: float, major_unit: Any) -> list[float]:
    """Значения делений оси по явному шагу или равномерно на 5 частей."""
    if isinstance(major_unit, (int, float)) and major_unit > 0:
        count = max(1, int(round((maximum - minimum) / major_unit)))
        steps = [minimum + major_unit * step for step in range(count + 1)]
        return [value for value in steps if minimum <= value <= maximum]
    return [maximum - (maximum - minimum) * step / 5 for step in range(6)]


def _chart_decorations(chart: dict[str, Any], series: list[dict[str, Any]]) -> str:
    chart_type = chart.get("chart_type")
    parts = []
    if chart.get("legend", True) and chart_type not in {"pieChart", "doughnutChart"}:
        parts.extend(_chart_legend(series, str(chart.get("legend_position") or "r")))
    category_title = chart.get("category_axis_title")
    value_title = chart.get("value_axis_title")
    horizontal = chart_type == "barChart" and chart.get("bar_direction") == "bar"
    if category_title:
        if horizontal:
            parts.append(
                '<text x="18" y="220" text-anchor="middle" font-family="Arial" font-size="13" '
                f'transform="rotate(-90 18 220)">{escape(str(category_title))}</text>'
            )
        else:
            parts.append(_svg_label(390, 425, str(category_title), anchor="middle"))
    if value_title:
        if horizontal:
            parts.append(_svg_label(390, 425, str(value_title), anchor="middle"))
        else:
            parts.append(
                '<text x="18" y="220" text-anchor="middle" font-family="Arial" font-size="13" '
                f'transform="rotate(-90 18 220)">{escape(str(value_title))}</text>'
            )
    secondary_value_title = chart.get("secondary_value_axis_title")
    if secondary_value_title:
        parts.append(
            '<text x="790" y="220" text-anchor="middle" font-family="Arial" font-size="13" '
            f'transform="rotate(90 790 220)">{escape(str(secondary_value_title))}</text>'
        )
    return "".join(parts)


def _chart_legend(series: list[dict[str, Any]], position: str) -> list[str]:
    parts = []
    for index, item in enumerate(series):
        if position in {"b", "t"}:
            x = 80 + index * 150
            y = 430 if position == "b" else 42
        else:
            x = 8 if position == "l" else 735
            y = 65 + index * 24
        parts.append(f'<rect x="{x}" y="{y}" width="12" height="12" fill="{item["color"]}"/>')
        parts.append(_svg_label(x + 17, y + 11, item["name"], anchor="start"))
    return parts


def _svg_label(x: float, y: float, value: str, *, anchor: str, fill: str | None = None) -> str:
    fill_attr = f' fill="{escape(fill, quote=True)}"' if fill else ' fill="#374151"'
    return (
        f'<text x="{x:g}" y="{y:g}" text-anchor="{anchor}" font-family="Arial" font-size="12"{fill_attr}>{escape(value)}</text>'
    )


def _chart_description(categories: list[str], series: list[dict[str, Any]]) -> str:
    rows = []
    for index, category in enumerate(categories):
        values = [str(item["values"][index]) for item in series if index < len(item["values"])]
        rows.append(f"{category}: {', '.join(values)}")
    return "; ".join(rows)


def _shape_svg_uri(shape: dict[str, Any]) -> str | None:
    """Вернуть data-URI SVG-фона автофигуры (viewBox 0..100) или None."""
    entry = _preset_geometry().get(shape.get("prst"))
    if entry is None:
        return None
    path_d, stroke_only = entry
    fill = shape.get("fill")
    fill_attr = "none" if stroke_only or fill in (None, "none", "blip") else fill
    if fill_attr and not _COLOR_RE.match(fill_attr):
        fill_attr = "none"
    line = shape.get("line") or {}
    stroke = line.get("color")
    if stroke and not _COLOR_RE.match(stroke):
        stroke = None
    if fill_attr == "none" and stroke is None:
        return None
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" preserveAspectRatio="none">']
    attributes = f' fill="{fill_attr}"'
    if stroke is not None:
        attributes += f' stroke="{stroke}"'
        width = line.get("width")
        if isinstance(width, (int, float)) and width > 0:
            attributes += f' stroke-width="{width * _PT_TO_PX:.3g}px" vector-effect="non-scaling-stroke"'
    elif stroke_only:
        attributes += ' stroke="#444444" stroke-width="1.5px"'
    parts.append(f'<path d="{path_d}"{attributes}/>')
    parts.append("</svg>")
    return "data:image/svg+xml," + quote("".join(parts), safe="")


def _css_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")


def _safe_link(value: str) -> str | None:
    scheme = urlsplit(value).scheme.lower()
    return value if scheme in {"", "http", "https", "mailto", "tel", "ftp"} else None


def _formula_to_mathml(formula: Formula) -> str:
    """Привести формулу к MathML: для OMML — конвертация из офисного разметки."""
    if formula.format is FormulaFormat.MATHML:
        return formula.value
    from textalchemy.convert.pptx_to_html._omml import convert_omml

    mathml = convert_omml(formula.value)
    if not mathml or "<math" not in mathml or "merror" in mathml:
        raise ValueError("OMML contains no convertible formula")
    return mathml


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
