"""Нативные линии тренда и планки погрешностей рядов диаграмм."""

from __future__ import annotations

import math
from typing import Any

from textalchemy.core.color import ColorValue
from textalchemy.core.diagnostics import IssueSeverity

C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
KINDS = {"barChart", "lineChart", "areaChart", "scatterChart", "bubbleChart"}


def _number(value: Any, *, minimum: float = 0) -> float:
    if isinstance(value, bool):
        raise ValueError("логическое значение вместо числа")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise ValueError("недопустимая величина")
    return number


def _line(parent: Any, settings: dict[str, Any]) -> None:
    from lxml import etree

    value = settings.get("color_value", settings.get("color"))
    if value is None:
        return
    if not isinstance(value, (str, dict)):
        raise ValueError("неподдержанный цвет линии")
    color = ColorValue.from_dict(value) if isinstance(value, dict) else ColorValue.from_hex(value)
    if color.alpha != 1 or color.icc_profile or color.blend_mode != "normal":
        raise ValueError("поддержан только непрозрачный RGB-цвет линии")
    props = etree.SubElement(parent, C + "spPr")
    line = etree.SubElement(props, A + "ln")
    fill = etree.SubElement(line, A + "solidFill")
    etree.SubElement(fill, A + "srgbClr", val=color.to_hex().lstrip("#"))


def _trend(settings: dict[str, Any]) -> Any:
    from lxml import etree

    allowed = {
        "name",
        "type",
        "order",
        "period",
        "forward",
        "backward",
        "intercept",
        "show_equation",
        "show_r_squared",
        "color",
        "color_value",
    }
    if set(settings) - allowed:
        raise ValueError("неподдержанные параметры линии тренда")
    kind = settings.get("type", "linear")
    if kind not in {"linear", "exp", "log", "poly", "power", "movingAvg"}:
        raise ValueError("неподдержанный тип тренда")
    result = etree.Element(C + "trendline")
    if "name" in settings:
        if not isinstance(settings["name"], str):
            raise ValueError("имя линии тренда должно быть строкой")
        etree.SubElement(result, C + "name").text = settings["name"]
    _line(result, settings)
    etree.SubElement(result, C + "trendlineType", val=kind)
    for key, expected, minimum, maximum in (("order", "poly", 2, 6), ("period", "movingAvg", 2, 255)):
        if key in settings or kind == expected:
            value = _number(settings.get(key, 2), minimum=minimum)
            if kind != expected or value != int(value) or value > maximum:
                raise ValueError(f"недопустимый {key}")
            etree.SubElement(result, C + key, val=str(int(value)))
    for key in ("forward", "backward", "intercept"):
        if key not in settings:
            continue
        if kind == "movingAvg" or (key == "intercept" and kind not in {"linear", "poly", "exp"}):
            raise ValueError(f"{key} не поддержан для {kind}")
        value = _number(settings[key], minimum=-math.inf if key == "intercept" else 0)
        if key == "intercept" and kind == "exp" and value <= 0:
            raise ValueError("пересечение экспоненциального тренда должно быть положительным")
        etree.SubElement(result, C + key, val=str(value))
    for key, tag in (("show_r_squared", "dispRSqr"), ("show_equation", "dispEq")):
        if key in settings:
            value = settings[key]
            if not isinstance(value, bool) or (kind == "movingAvg" and value):
                raise ValueError(f"недопустимый {key}")
            etree.SubElement(result, C + tag, val="1" if value else "0")
    return result


def _errors(settings: dict[str, Any], kind: str, direction: str, count: int) -> Any:
    from lxml import etree

    if set(settings) - {"direction", "bar_type", "value_type", "value", "color", "color_value", "plus", "minus"}:
        raise ValueError("неподдержанные параметры погрешностей")
    default_direction = direction
    direction = settings.get("direction", direction)
    mode, value_type = settings.get("bar_type", "both"), settings.get("value_type", "fixedVal")
    if direction not in {"x", "y"} or (kind not in {"scatterChart", "bubbleChart"} and direction != default_direction):
        raise ValueError("неподдержанное направление погрешностей")
    if mode not in {"both", "plus", "minus"} or value_type not in {"fixedVal", "percentage", "stdDev", "stdErr", "cust"}:
        raise ValueError("неподдержанный тип погрешностей")
    result = etree.Element(C + "errBars")
    for tag, value in (("errDir", direction), ("errBarType", mode), ("errValType", value_type)):
        etree.SubElement(result, C + tag, val=value)
    if value_type != "cust" and ("plus" in settings or "minus" in settings):
        raise ValueError("массивы допустимы только для пользовательских погрешностей")
    if value_type == "cust":
        if "value" in settings:
            raise ValueError("пользовательские погрешности не принимают общую величину")
        for side in ("plus", "minus"):
            if side in settings or mode in {"both", side}:
                _custom_values(result, side, settings.get(side), count)
    elif value_type == "stdErr":
        if "value" in settings:
            raise ValueError("стандартная ошибка не принимает величину")
    else:
        value = _number(settings.get("value", 1))
        etree.SubElement(result, C + "val", val=str(value))
    _line(result, settings)
    return result


def _custom_values(parent: Any, side: str, values: Any, count: int) -> None:
    from lxml import etree

    if not isinstance(values, (list, tuple)) or len(values) != count or not 0 < count <= 100000:
        raise ValueError(f"массив {side} должен соответствовать числу точек ряда")
    target = etree.SubElement(parent, C + side)
    literal = etree.SubElement(target, C + "numLit")
    etree.SubElement(literal, C + "formatCode").text = "General"
    etree.SubElement(literal, C + "ptCount", val=str(count))
    for index, value in enumerate(values):
        if value is None:
            continue
        number = _number(value)
        point = etree.SubElement(literal, C + "pt", idx=str(index))
        etree.SubElement(point, C + "v").text = str(number)


def configure_statistics(*, source: dict[str, Any], target: Any, options: dict[str, Any], report: Any, location: str) -> None:
    kind = source.get("chart_type", options.get("chart_type"))
    direction = (
        "x" if kind == "barChart" and source.get("plot", {}).get("bar_direction", options.get("bar_direction")) == "bar" else "y"
    )
    for key in ("trendline", "error_bars"):
        settings = source.get(key)
        if settings is None:
            continue
        try:
            if kind not in KINDS:
                raise ValueError("неподдержанный ряд или настройки")
            if key == "trendline" and source.get("plot", {}).get("grouping", options.get("grouping")) in {
                "stacked",
                "percentStacked",
            }:
                raise ValueError("тренд накопительного ряда не поддержан")
            if key == "trendline":
                items = settings if isinstance(settings, list) else [settings]
                if not 1 <= len(items) <= 64 or any(not isinstance(item, dict) for item in items):
                    raise ValueError("неподдержанные настройки тренда")
                elements = [_trend(item) for item in items]
            else:
                items = settings if isinstance(settings, list) else [settings]
                if not items or len(items) > (2 if kind in {"scatterChart", "bubbleChart"} else 1):
                    raise ValueError("неподдержанное число направлений погрешностей")
                directions = set()
                elements = []
                for item in items:
                    if not isinstance(item, dict):
                        raise ValueError("неподдержанные настройки погрешностей")
                    axis = item.get("direction", direction)
                    if axis in directions:
                        raise ValueError("повторное направление погрешностей")
                    directions.add(axis)
                    elements.append(_errors(item, kind, direction, len(source.get("values", []))))
            for element in elements:
                before = ("c:errBars",) if key == "trendline" else ()
                target._element.insert_element_before(
                    element, *before, "c:cat", "c:val", "c:xVal", "c:yVal", "c:bubbleSize", "c:extLst"
                )
        except (TypeError, ValueError, OverflowError) as error:
            report.add(IssueSeverity.LOSS, "charts", f"{key} не перенесены: {error}.", location)
