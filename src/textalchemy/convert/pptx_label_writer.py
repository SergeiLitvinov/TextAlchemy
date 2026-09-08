"""Нативные подписи данных на уровне набора диаграмм и отдельного ряда."""

from __future__ import annotations

from typing import Any

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity

C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
FLAGS = {
    "hidden": "delete",
    "show_legend_key": "showLegendKey",
    "show_value": "showVal",
    "show_category": "showCatName",
    "show_series": "showSerName",
    "show_percent": "showPercent",
    "show_bubble_size": "showBubbleSize",
    "show_leader_lines": "showLeaderLines",
}


def configure_labels(*, chart: Any, data: dict[str, Any], report: ConversionReport, location: str) -> None:
    offset = 0
    for index, plot in enumerate(chart.plots):
        sources = data["series"][offset : offset + len(plot.series)]
        settings = data.get("data_labels") if index == 0 else sources[0].get("plot", {}).get("data_labels")
        if settings is not None:
            _write_labels(plot._element, settings, report, location)
        for source, target in zip(sources, plot.series):
            if "data_labels" in source:
                _write_labels(target._element, source["data_labels"], report, location)
        offset += len(plot.series)


def _write_labels(parent: Any, settings: Any, report: ConversionReport, location: str) -> None:
    from lxml import etree

    if not isinstance(settings, dict):
        report.add(IssueSeverity.LOSS, "styles", "Настройки подписей данных должны быть словарём.", location)
        return
    labels = etree.Element(C + "dLbls")

    def invalid(key: str) -> None:
        report.add(IssueSeverity.LOSS, "styles", f"Свойство подписи данных {key} не перенесено: неверное значение.", location)

    def flag(key: str) -> None:
        if key not in settings:
            return
        if not isinstance(settings[key], bool):
            invalid(key)
            return
        etree.SubElement(labels, C + FLAGS[key], val="1" if settings[key] else "0")

    flag("hidden")
    if "num_format" in settings:
        if isinstance(settings["num_format"], str) and isinstance(settings.get("num_format_linked", True), bool):
            etree.SubElement(
                labels,
                C + "numFmt",
                formatCode=settings["num_format"],
                sourceLinked="1" if settings.get("num_format_linked", True) else "0",
            )
        else:
            invalid("num_format")
    if "position" in settings:
        if settings["position"] in ("bestFit", "b", "ctr", "inBase", "inEnd", "l", "outEnd", "r", "t"):
            etree.SubElement(labels, C + "dLblPos", val=settings["position"])
        else:
            invalid("position")
    for key in FLAGS:
        if key not in ("hidden", "show_leader_lines"):
            flag(key)
    if "separator" in settings:
        if isinstance(settings["separator"], str):
            etree.SubElement(labels, C + "separator").text = settings["separator"]
        else:
            invalid("separator")
    flag("show_leader_lines")
    old = parent.find(C + "dLbls")
    if old is not None:
        parent.remove(old)
    if parent.tag == C + "scatterChart":
        parent.insert_element_before(labels, "c:axId", "c:extLst")
    else:
        placeholder = parent.get_or_add_dLbls()
        parent.replace(placeholder, labels)
