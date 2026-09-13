"""Чтение числовых массивов диаграммы с сохранением пропущенных индексов."""

from __future__ import annotations

from typing import Any

C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"


def indexed_numbers(node: Any) -> list[str | None]:
    if node is None:
        return []
    cache = node.find(C + "numLit")
    if cache is None:
        cache = node.find(f"{C}numRef/{C}numCache")
    if cache is None:
        return []
    try:
        count_node = cache.find(C + "ptCount")
        count = int(count_node.get("val")) if count_node is not None else 0
        values = {}
        for point in cache.findall(C + "pt"):
            index = int(point.get("idx", "-1"))
            if index < 0 or index >= 100000 or index in values:
                return []
            value = point.find(C + "v")
            values[index] = value.text if value is not None else None
        if count_node is None:
            count = max(values, default=-1) + 1
        if not 0 <= count <= 100000 or any(index >= count for index in values):
            return []
        return [values.get(index) for index in range(count)]
    except (ValueError, TypeError):
        return []
