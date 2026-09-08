"""Native axis scales and titles, independent of chart data/workbook generation."""

import math

from textalchemy.core.diagnostics import IssueSeverity

C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"


def configure_chart(chart, data, report, location):
    from pptx.chart.axis import CategoryAxis, ValueAxis
    from pptx.enum.chart import XL_LEGEND_POSITION

    chart.has_legend = bool(data.get("legend"))
    if chart.has_legend:
        positions = {
            "b": XL_LEGEND_POSITION.BOTTOM,
            "t": XL_LEGEND_POSITION.TOP,
            "l": XL_LEGEND_POSITION.LEFT,
            "r": XL_LEGEND_POSITION.RIGHT,
        }
        chart.legend.position = positions.get(data.get("legend_position"), XL_LEGEND_POSITION.RIGHT)
    axes = data.get("axes", {})
    numeric = data.get("chart_type") in ("scatterChart", "bubbleChart")
    values = chart._chartSpace.findall(".//" + C + "plotArea/" + C + "valAx")
    categories = chart._chartSpace.findall(".//" + C + "plotArea/" + C + "catAx")
    targets = {}
    if numeric and len(values) >= 2:
        targets = {"x": ValueAxis(values[0]), "y": ValueAxis(values[1])}
    elif not numeric:
        if categories:
            targets["category"] = CategoryAxis(categories[0])
        if values:
            targets["value"] = ValueAxis(values[0])
        if len(values) > 1:
            targets["secondary_value"] = ValueAxis(values[1])
    for name, axis in targets.items():
        settings = axes.get(name, {})
        if not settings:
            continue
        try:
            _axis(axis, settings)
        except (ValueError, TypeError, AttributeError):
            report.add(IssueSeverity.LOSS, "charts", f"Настройки оси {name} перенесены не полностью.", location)


def _axis(axis, settings):
    from lxml import etree

    for key, attribute in (
        ("min", "minimum_scale"),
        ("max", "maximum_scale"),
        ("major_unit", "major_unit"),
        ("minor_unit", "minor_unit"),
    ):
        if key in settings:
            value = float(settings[key])
            if not math.isfinite(value) or (key.endswith("unit") and value <= 0):
                raise ValueError("invalid axis scale")
            setattr(axis, attribute, value)
    if settings.get("title"):
        axis.has_title = True
        axis.axis_title.text_frame.text = settings["title"]
    if "reverse_order" in settings:
        axis.reverse_order = settings["reverse_order"]
    if "num_format" in settings:
        axis.tick_labels.number_format = settings["num_format"]
        axis.tick_labels.number_format_is_linked = settings.get("num_format_linked", False)
    if "hidden" in settings:
        axis.visible = not settings["hidden"]
    if "log_base" in settings:
        base = float(settings["log_base"])
        if not 2 <= base <= 1000:
            raise ValueError("invalid logarithmic base")
        scaling = axis._element.scaling
        scaling.insert(0, etree.Element(C + "logBase", val=str(base)))
