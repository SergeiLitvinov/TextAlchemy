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


def _chart_svg(chart: dict[str, Any]) -> str | None:
    chart_type = chart.get("chart_type")
    categories = [str(value) for value in chart.get("categories") or []]
    series = _numeric_chart_series(chart.get("series"))
    if not series:
        return None
    if not categories:
        categories = [str(index + 1) for index in range(max(len(item["values"]) for item in series))]
    grouping = chart.get("grouping")
    axes = chart.get("axes") or {}
    value_axis = axes.get("value") or {}
    axis_style = _chart_axis_style(series, value_axis)
    axis_style["gap_width"] = chart.get("gap_width", 150.0)
    axis_style["overlap"] = chart.get("overlap", 0.0)
    label_style = {
        "chart": chart.get("data_labels") or {},
        "formatter": _number_formatter(chart.get("data_labels", {}).get("num_format")),
    }
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
            )
        else:
            body = _bar_chart_svg(categories, series, horizontal=horizontal, axis_style=axis_style, label_style=label_style)
    elif chart_type == "lineChart" and grouping in {None, "standard"}:
        body = _line_chart_svg(categories, series, axis_style=axis_style, label_style=label_style)
    elif chart_type in {"pieChart", "doughnutChart"}:
        body = _pie_chart_svg(
            categories,
            series[0],
            doughnut=chart_type == "doughnutChart",
            show_legend=bool(chart.get("legend", True)),
            label_style=label_style,
        )
    else:
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
        minimum = min(minimum, value_axis["min"])
    if not value_axis.get("auto_max") and isinstance(value_axis.get("max"), (int, float)):
        maximum = max(maximum, value_axis["max"])
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
) -> str:
    if horizontal:
        return _horizontal_bar_chart_svg(categories, series, axis_style=axis_style, label_style=label_style)
    left, top, width, height = 65.0, 55.0, 650.0, 320.0
    minimum, maximum = axis_style["minimum"], axis_style["maximum"]
    baseline = top + height * maximum / (maximum - minimum)
    category_width = width / max(len(categories), 1)
    series_count = max(len(series), 1)
    gap_width = axis_style.get("gap_width", 150.0) / 100.0
    overlap = axis_style.get("overlap", 0.0) / 100.0
    bar_width = category_width / (series_count + gap_width)
    bar_step = bar_width * (1.0 - overlap)
    cluster_width = (series_count - 1) * bar_step + bar_width
    parts = _chart_grid(left, top, width, height, minimum, maximum, axis_style)
    chart_labels = label_style["chart"]
    for category_index, category in enumerate(categories):
        group_x = left + category_index * category_width + (category_width - cluster_width) / 2
        for series_index, item in enumerate(series):
            value = item["values"][category_index] if category_index < len(item["values"]) else 0.0
            value_y = top + height * (maximum - value) / (maximum - minimum)
            y = min(value_y, baseline)
            bar_height = max(abs(baseline - value_y), 0.75)
            x = group_x + series_index * bar_step
            parts.append(
                f'<rect x="{x:g}" y="{y:g}" width="{bar_width:g}" height="{bar_height:g}" '
                f'fill="{item["color"]}"><title>{escape(item["name"])}: {value:g}</title></rect>'
            )
            _append_bar_label(parts, item, value, None, category, x + bar_width / 2, y, chart_labels, anchor="middle")
        parts.append(_svg_label(left + (category_index + 0.5) * category_width, 397, category, anchor="middle"))
    return "".join(parts)


def _horizontal_bar_chart_svg(
    categories: list[str],
    series: list[dict[str, Any]],
    *,
    axis_style: dict[str, Any],
    label_style: dict[str, Any],
) -> str:
    left, top, width, height = 120.0, 55.0, 595.0, 320.0
    minimum, maximum = axis_style["minimum"], axis_style["maximum"]
    baseline = left + width * (-minimum) / (maximum - minimum)
    category_height = height / max(len(categories), 1)
    series_count = max(len(series), 1)
    gap_width = axis_style.get("gap_width", 150.0) / 100.0
    overlap = axis_style.get("overlap", 0.0) / 100.0
    bar_height = category_height / (series_count + gap_width)
    bar_step = bar_height * (1.0 - overlap)
    cluster_height = (series_count - 1) * bar_step + bar_height
    parts = [f'<line x1="{baseline:g}" y1="{top:g}" x2="{baseline:g}" y2="{top + height:g}" stroke="#6B7280"/>']
    chart_labels = label_style["chart"]
    for category_index, category in enumerate(categories):
        group_y = top + category_index * category_height + (category_height - cluster_height) / 2
        parts.append(_svg_label(left - 8, top + (category_index + 0.5) * category_height, category, anchor="end"))
        for series_index, item in enumerate(series):
            value = item["values"][category_index] if category_index < len(item["values"]) else 0.0
            value_x = left + width * (value - minimum) / (maximum - minimum)
            x = min(value_x, baseline)
            bar_width = max(abs(value_x - baseline), 0.75)
            y = group_y + series_index * bar_step
            parts.append(
                f'<rect x="{x:g}" y="{y:g}" width="{bar_width:g}" height="{bar_height:g}" '
                f'fill="{item["color"]}"><title>{escape(item["name"])}: {value:g}</title></rect>'
            )
            if value >= 0:
                label_x, anchor = value_x + 4, "start"
            else:
                label_x, anchor = value_x - 4, "end"
            _append_bar_label(
                parts, item, value, None, category, label_x, y + bar_height * 0.45, chart_labels, anchor=anchor
            )
    return "".join(parts)


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
) -> str:
    left, top, width, height = 65.0, 55.0, 650.0, 320.0
    minimum, maximum = axis_style["minimum"], axis_style["maximum"]
    parts = _chart_grid(left, top, width, height, minimum, maximum, axis_style)
    denominator = max(len(categories) - 1, 1)
    chart_labels = label_style["chart"]
    for item in series:
        points = []
        circles = []
        for index, value in enumerate(item["values"][: len(categories)]):
            x = left + width * index / denominator
            y = top + height * (maximum - value) / (maximum - minimum)
            points.append(f"{x:g},{y:g}")
            circles.append(
                f'<circle cx="{x:g}" cy="{y:g}" r="4" fill="{item["color"]}">'
                f"<title>{escape(item['name'])}: {value:g}</title></circle>"
            )
            _append_bar_label(parts, item, value, None, categories[index], x, y, chart_labels, anchor="middle")
        parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{item["color"]}" stroke-width="3"/>')
        parts.extend(circles)
    for index, category in enumerate(categories):
        parts.append(_svg_label(left + width * index / denominator, 397, category, anchor="middle"))
    return "".join(parts)


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
    minimum, maximum = axis_style["minimum"], axis_style["maximum"]
    bar_items = [item for item in series if item.get("chart_type") in {None, "barChart"}]
    line_items = [item for item in series if item.get("chart_type") == "lineChart"]
    parts = _chart_grid(left, top, width, height, minimum, maximum, axis_style)
    chart_labels = label_style["chart"]
    denominator = max(len(categories) - 1, 1)
    if bar_items:
        baseline = top + height * maximum / (maximum - minimum)
        category_width = width / max(len(categories), 1)
        series_count = max(len(bar_items), 1)
        gap_width = axis_style.get("gap_width", 150.0) / 100.0
        overlap = axis_style.get("overlap", 0.0) / 100.0
        bar_width = category_width / (series_count + gap_width)
        bar_step = bar_width * (1.0 - overlap)
        cluster_width = (series_count - 1) * bar_step + bar_width
        for category_index, category in enumerate(categories):
            group_x = left + category_index * category_width + (category_width - cluster_width) / 2
            for series_index, item in enumerate(bar_items):
                value = item["values"][category_index] if category_index < len(item["values"]) else 0.0
                value_y = top + height * (maximum - value) / (maximum - minimum)
                y = min(value_y, baseline)
                bar_height = max(abs(baseline - value_y), 0.75)
                x = group_x + series_index * bar_step
                parts.append(
                    f'<rect x="{x:g}" y="{y:g}" width="{bar_width:g}" height="{bar_height:g}" '
                    f'fill="{item["color"]}"><title>{escape(item["name"])}: {value:g}</title></rect>'
                )
                _append_bar_label(parts, item, value, None, category, x + bar_width / 2, y, chart_labels, anchor="middle")
    for item in line_items:
        points = []
        circles = []
        for index, value in enumerate(item["values"][: len(categories)]):
            x = left + width * index / denominator
            y = top + height * (maximum - value) / (maximum - minimum)
            points.append(f"{x:g},{y:g}")
            circles.append(
                f'<circle cx="{x:g}" cy="{y:g}" r="4" fill="{item["color"]}">'
                f"<title>{escape(item['name'])}: {value:g}</title></circle>"
            )
            _append_bar_label(parts, item, value, None, categories[index], x, y, chart_labels, anchor="middle")
        parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{item["color"]}" stroke-width="3"/>')
        parts.extend(circles)
    for index, category in enumerate(categories):
        parts.append(_svg_label(left + (index + 0.5) * width / max(len(categories), 1), 397, category, anchor="middle"))
    return "".join(parts)


def _pie_chart_svg(
    categories: list[str],
    series: dict[str, Any],
    *,
    doughnut: bool,
    show_legend: bool,
    label_style: dict[str, Any],
) -> str:
    values = [max(value, 0.0) for value in series["values"][: len(categories)]]
    total = sum(values)
    if total <= 0:
        return _svg_label(400, 220, "No positive data", anchor="middle")
    center_x, center_y, radius = 310.0, 225.0, 145.0
    angle = -math.pi / 2
    parts = []
    labels, formatter = _series_label_context(series, label_style["chart"])
    for index, (category, value) in enumerate(zip(categories, values, strict=False)):
        sweep = 2 * math.pi * value / total
        end = angle + sweep
        x1, y1 = center_x + radius * math.cos(angle), center_y + radius * math.sin(angle)
        x2, y2 = center_x + radius * math.cos(end), center_y + radius * math.sin(end)
        large = 1 if sweep > math.pi else 0
        color = series.get("color") or _CHART_COLORS[index % len(_CHART_COLORS)]
        path = f"M {center_x:g} {center_y:g} L {x1:g} {y1:g} A {radius:g} {radius:g} 0 {large} 1 {x2:g} {y2:g} Z"
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
            label_y = center_y + label_radius * math.sin(mid)
            parts.append(_svg_label(label_x, label_y + 4, text, anchor="middle", fill=fill))
        if show_legend:
            parts.append(f'<rect x="500" y="{85 + index * 26:g}" width="14" height="14" fill="{color}"/>')
            parts.append(_svg_label(522, 97 + index * 26, category, anchor="start"))
        angle = end
    if doughnut:
        parts.append('<circle cx="310" cy="225" r="72" fill="white"/>')
    return "".join(parts)


def _stacked_bar_chart_svg(
    categories: list[str],
    series: list[dict[str, Any]],
    *,
    horizontal: bool,
    percent: bool,
    axis_style: dict[str, Any],
    label_style: dict[str, Any],
) -> str:
    values, minimum, maximum = _stacked_values(categories, series, percent=percent)
    if percent:
        minimum = axis_style["minimum"]
        maximum = axis_style["maximum"]
    if horizontal:
        return _horizontal_stacked_bars(
            categories, series, values, minimum, maximum, percent=percent, axis_style=axis_style, label_style=label_style
        )
    left, top, width, height = 65.0, 55.0, 650.0, 320.0
    category_width = width / max(len(categories), 1)
    gap_width = axis_style.get("gap_width", 150.0) / 100.0
    bar_width = category_width / (1.0 + gap_width)
    parts = _chart_grid(left, top, width, height, minimum, maximum, axis_style)
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
            parts.append(
                f'<rect x="{x:g}" y="{y:g}" width="{bar_width:g}" height="{segment_height:g}" '
                f'fill="{item["color"]}"><title>{escape(item["name"])}: {original:g}</title></rect>'
            )
            total_value = _stack_total(values, category_index, value)
            segment_percent = 100.0 * value / total_value if total_value else 0.0
            percent_label = segment_percent if percent or segment_percent != 0.0 else None
            _append_bar_label(
                parts, item, original, percent_label, category, x + bar_width / 2, y, chart_labels, anchor="middle"
            )
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
) -> str:
    left, top, width, height = 120.0, 55.0, 595.0, 320.0
    category_height = height / max(len(categories), 1)
    gap_width = axis_style.get("gap_width", 150.0) / 100.0
    bar_height = category_height / (1.0 + gap_width)
    baseline = left + width * (-minimum) / (maximum - minimum)
    parts = [f'<line x1="{baseline:g}" y1="{top:g}" x2="{baseline:g}" y2="{top + height:g}" stroke="#6B7280"/>']
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
    major_unit = axis_style.get("major_unit")
    parts = []
    steps: list[float]
    if isinstance(major_unit, (int, float)) and major_unit > 0:
        count = max(1, int(round((maximum - minimum) / major_unit)))
        steps = [minimum + major_unit * step for step in range(count + 1)]
        steps = [value for value in steps if minimum <= value <= maximum]
    else:
        steps = [maximum - (maximum - minimum) * step / 5 for step in range(6)]
    for value in steps:
        fraction = (maximum - value) / (maximum - minimum)
        y = top + height * fraction
        parts.append(f'<line x1="{left:g}" y1="{y:g}" x2="{left + width:g}" y2="{y:g}" stroke="#D1D5DB"/>')
        if show_labels:
            parts.append(_svg_label(left - 8, y + 4, formatter(value), anchor="end"))
    return parts


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
        f'<text x="{x:g}" y="{y:g}" text-anchor="{anchor}" font-family="Arial" font-size="12"{fill_attr}>'
        f"{escape(value)}</text>"
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
