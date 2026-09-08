"""Нативная геометрия столбцов и секторов с независимостью наборов диаграммы."""

from __future__ import annotations

from typing import Any

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity

C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
NUMERIC_SETTINGS = {
    "gap_width": ("gapWidth", 0, 500, ("barChart",), ("c:overlap", "c:serLines", "c:axId", "c:extLst")),
    "overlap": ("overlap", -100, 100, ("barChart",), ("c:serLines", "c:axId", "c:extLst")),
    "first_slice_angle": ("firstSliceAng", 0, 360, ("pieChart", "doughnutChart"), ("c:holeSize", "c:extLst")),
    "hole_size": ("holeSize", 10, 90, ("doughnutChart",), ("c:extLst",)),
}


def configure_plots(*, chart: Any, data: dict[str, Any], report: ConversionReport, location: str) -> None:
    offset = 0
    for index, plot in enumerate(chart.plots):
        sources = data["series"][offset : offset + len(plot.series)]
        settings = data if index == 0 else sources[0].get("plot", {})
        for source in sources[1:] if index else []:
            for key in (*NUMERIC_SETTINGS, "vary_colors"):
                if source.get("plot", {}).get(key) != settings.get(key):
                    report.add(
                        IssueSeverity.LOSS, "styles", f"Противоречивое свойство набора {key}: использован первый ряд.", location
                    )
        _configure(plot._element, settings, report, location)
        offset += len(plot.series)


def _configure(parent: Any, settings: dict[str, Any], report: ConversionReport, location: str) -> None:
    from lxml import etree

    def replace(tag: str, value: str, successors: tuple[str, ...]) -> None:
        old = parent.find(C + tag)
        if old is not None:
            parent.remove(old)
        parent.insert_element_before(etree.Element(C + tag, val=value), *successors)

    for key, (tag, minimum, maximum, kinds, successors) in NUMERIC_SETTINGS.items():
        if key not in settings:
            continue
        try:
            value = float(settings[key])
            if isinstance(settings[key], bool) or parent.tag not in {C + kind for kind in kinds}:
                raise ValueError("unsupported property")
            if not minimum <= value <= maximum or not value.is_integer():
                raise ValueError("invalid value")
        except (TypeError, ValueError, OverflowError):
            report.add(
                IssueSeverity.LOSS,
                "styles",
                f"Свойство диаграммы {key} не перенесено: неверное значение или тип диаграммы.",
                location,
            )
            continue
        replace(tag, str(int(value)), successors)
    if "vary_colors" in settings:
        if isinstance(settings["vary_colors"], bool):
            replace("varyColors", "1" if settings["vary_colors"] else "0", ("c:ser", "c:dLbls", "c:axId", "c:extLst"))
        else:
            report.add(IssueSeverity.LOSS, "styles", "Свойство диаграммы vary_colors должно быть логическим.", location)
