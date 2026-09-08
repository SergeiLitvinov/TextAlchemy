"""Indexed chart caches: preserve absent points and numeric XY dimensions."""

from __future__ import annotations

from typing import Any

C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"


def cached_values(node):
    if node is None:
        return []
    points = node.findall(".//" + C + "pt")
    count = node.find(".//" + C + "ptCount")
    length = int(count.get("val", "0")) if count is not None else 0
    indexed = [(int(point.get("idx", str(position))), point) for position, point in enumerate(points)]
    length = max(length, max((index + 1 for index, _ in indexed), default=0))
    if not 0 <= length <= 100000:
        raise ValueError("chart cache exceeds 100000 points")
    result = [None] * length
    for index, point in indexed:
        if index < 0:
            raise ValueError("negative chart point index")
        value = point.find(C + "v")
        result[index] = value.text if value is not None else None
    return result


def numeric_series(series):
    result = {
        key: cached_values(series.find(C + tag))
        for tag, key in (
            ("xVal", "x_values"),
            ("yVal", "values"),
            ("bubbleSize", "bubble_sizes"),
        )
        if series.find(C + tag) is not None
    }
    marker = series.find(C + "marker/" + C + "symbol")
    if marker is not None:
        result["marker_symbol"] = marker.get("val")
    return result


def plot_settings(node):
    result = {}
    for tag, key in (("grouping", "grouping"), ("barDir", "bar_direction")):
        element = node.find(C + tag)
        if element is not None:
            result[key] = element.get("val")
    return result


def plot_appearance(node: Any) -> dict[str, Any]:
    """Прочитать явную геометрию столбцов и секторов отдельного набора."""
    result = {}
    for tag, key in (
        ("gapWidth", "gap_width"),
        ("overlap", "overlap"),
        ("firstSliceAng", "first_slice_angle"),
        ("holeSize", "hole_size"),
    ):
        element = node.find(C + tag)
        if element is not None and element.get("val") is not None:
            try:
                result[key] = float(element.get("val"))
            except ValueError:
                continue
    vary = node.find(C + "varyColors")
    if vary is not None:
        result["vary_colors"] = vary.get("val", "1").lower() in {"1", "true"}
    return result
