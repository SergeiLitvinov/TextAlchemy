"""Compose native category plots against one shared embedded workbook."""

from copy import deepcopy
from itertools import groupby

C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"


def is_combo(data):
    return bool(data.get("combo_types")) or any(
        series.get("axis") == "secondary_value" or series.get("chart_type", data.get("chart_type")) != data.get("chart_type")
        for series in data.get("series", [])
    )


def compose_combo(data, chart_data, kind_for):
    """Build all XML before publishing a shape; series indices keep workbook column identity."""
    from pptx.chart.xmlwriter import ChartXmlWriter
    from pptx.oxml import parse_xml

    def key(pair):
        _, series = pair
        plot = series.get("plot", {})
        return (
            series.get("chart_type", data.get("chart_type")),
            series.get("axis", "value"),
            plot.get("grouping", data.get("grouping", "standard")),
            plot.get("bar_direction", data.get("bar_direction", "col")),
            series.get("plot_index"),
        )

    groups = [(identity, list(rows)) for identity, rows in groupby(enumerate(data["series"]), key=key)]
    if not groups or groups[0][0][1] != "value":
        raise ValueError("primary plot must be first")
    declared = data.get("combo_types")
    if declared and list(declared) != [identity[0] for identity, _ in groups]:
        raise ValueError("plot metadata does not match series")
    horizontal = any(identity[0] == "barChart" and identity[3] == "bar" for identity, _ in groups)
    if horizontal and any(identity[0] != "barChart" or identity[3] != "bar" for identity, _ in groups):
        raise ValueError("horizontal bars require consistently horizontal category plots")
    plots, axes = [], []
    primary_ids, secondary_ids = ("1001", "1002"), ("1003", "1004")
    secondary = False
    for (kind, axis, grouping, direction, _), rows in groups:
        if kind not in ("barChart", "lineChart", "areaChart") or axis not in ("value", "secondary_value"):
            raise ValueError("unsupported combination")
        if kind == "barChart" and direction not in ("col", "bar"):
            raise ValueError("unknown bar direction")
        options = {**data, "chart_type": kind, "grouping": grouping, "bar_direction": direction}
        template = parse_xml(ChartXmlWriter(kind_for(options), chart_data).xml.encode("utf-8"))
        area = template.find(".//" + C + "plotArea")
        plot = area.find(C + kind)
        selected = {index for index, _ in rows}
        for series in list(plot.findall(C + "ser")):
            if int(series.find(C + "idx").get("val")) not in selected:
                plot.remove(series)
        ids = secondary_ids if axis == "secondary_value" else primary_ids
        for element, identity in zip(plot.findall(C + "axId"), ids):
            element.set("val", identity)
        plots.append(deepcopy(plot))
        if not axes:
            axes = [deepcopy(area.find(C + tag)) for tag in ("catAx", "valAx")]
            _axis_ids(axes, primary_ids)
        secondary = secondary or axis == "secondary_value"
    if secondary:
        extra = [deepcopy(element) for element in axes]
        _axis_ids(extra, secondary_ids)
        extra[0].find(C + "delete").set("val", "1")
        extra[0].find(C + "crosses").set("val", "max")
        extra[1].find(C + "axPos").set("val", "t" if horizontal else "r")
        axes.extend(extra)
    return plots, axes


def _axis_ids(axes, ids):
    for index, axis in enumerate(axes):
        axis.find(C + "axId").set("val", ids[index])
        axis.find(C + "crossAx").set("val", ids[1 - index])


def install_combo(chart, scene):
    area = chart._chartSpace.find(".//" + C + "plotArea")
    for element in list(area):
        if element.tag.endswith("Chart") or element.tag in {C + "catAx", C + "valAx", C + "dateAx", C + "serAx"}:
            area.remove(element)
    index = 1 if area.find(C + "layout") is not None else 0
    for element in (*scene[0], *scene[1]):
        area.insert(index, element)
        index += 1
