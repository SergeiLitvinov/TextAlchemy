"""Перенос явной заливки точек и отрыва секторов в нативные диаграммы."""

from __future__ import annotations

from typing import Any

from textalchemy.convert.pptx_text_writer import set_color
from textalchemy.core.diagnostics import ConversionReport, IssueSeverity


def configure_points(*, source: dict[str, Any], target: Any, kind: str, report: ConversionReport, location: str) -> None:
    from lxml import etree

    points = source.get("data_points", {})
    if not isinstance(points, dict):
        report.add(IssueSeverity.LOSS, "styles", "Некорректное оформление точек диаграммы пропущено.", location)
        return
    for key, settings in points.items():
        try:
            index = int(key)
            if isinstance(key, bool) or str(index) != str(key) or not 0 <= index < len(source["values"]):
                raise ValueError("invalid point index")
            if not isinstance(settings, dict):
                raise ValueError("invalid point settings")
        except (ValueError, TypeError):
            report.add(IssueSeverity.LOSS, "styles", f"Оформление точки {key} пропущено: неверный индекс или свойства.", location)
            continue
        point = target.points[index]
        color = settings.get("color_value", settings.get("color"))
        if color is not None:
            point.format.fill.solid()
            set_color(point.format.fill.fore_color, color, report, location)
        if "explosion" not in settings:
            continue
        try:
            explosion = float(settings["explosion"])
            if kind not in ("pieChart", "doughnutChart") or not 0 <= explosion <= 400 or not explosion.is_integer():
                raise ValueError("invalid point explosion")
        except (ValueError, TypeError):
            report.add(
                IssueSeverity.LOSS, "styles", f"Отрыв сектора {key} не перенесён: неподдержанное значение или тип.", location
            )
            continue
        element = target._element.get_or_add_dPt_for_point(index)
        node = etree.Element("{http://schemas.openxmlformats.org/drawingml/2006/chart}explosion", val=str(int(explosion)))
        element.insert_element_before(node, "c:spPr", "c:pictureOptions", "c:extLst")
