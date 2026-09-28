"""Crop an imported rectangular PDF table on existing cell boundaries."""
from copy import deepcopy
from math import isfinite


def describe_table(block: dict) -> dict | None:
    if block.get("type") != "table":
        return None
    rows = block["rows"]
    columns = len(rows[0]["cells"]) if rows else 0
    boxes = block.get("properties", {}).get("pdf", {}).get("cell_bboxes", [])
    if not columns or len(boxes) != len(rows) * columns:
        return None
    if any(len(row["cells"]) != columns or any(c["row_span"] != 1 or c["column_span"] != 1 for c in row["cells"])
           for row in rows):
        return None
    if any(not box or len(box) != 4 or not all(isfinite(x) for x in box) or box[0] >= box[2] or box[1] >= box[3]
           for box in boxes):
        return None
    # Only a regular grid: cropping a range must not cut across merged or irregular cells.
    for r in range(len(rows)):
        for c in range(columns):
            box = boxes[r * columns + c]
            if any(abs(box[i] - boxes[c][i]) > 0.1 for i in (0, 2)):
                return None
            if any(abs(box[i] - boxes[r * columns][i]) > 0.1 for i in (1, 3)):
                return None
    texts = [["\n".join("".join(run.get("text", "") for run in part.get("content", []))
                         for part in cell["blocks"]) for cell in row["cells"]] for row in rows]
    return {"rows": len(rows), "columns": columns, "cells": texts, "boxes": boxes}


def apply_table_ranges(value: dict, changes: dict[str, list[int]]) -> None:
    blocks = {block_id: block for ids, section in zip(value["order"], value["model"]["document"]["sections"], strict=True)
              for block_id, block in zip(ids, section["blocks"], strict=True)}
    originals = value.get("table_originals", {})
    prepared = []
    for block_id, bounds in changes.items():
        if block_id not in blocks:
            raise ValueError("Неизвестная таблица")
        original = originals.get(block_id, blocks[block_id])
        info = describe_table(original)
        if info is None:
            raise ValueError("Границы доступны только для прямоугольной PDF-таблицы без объединённых ячеек")
        if len(bounds) != 4 or any(type(n) is not int for n in bounds):
            raise ValueError("Укажите первую и последнюю строку и столбец целыми числами")
        r0, r1, c0, c1 = bounds
        if not (1 <= r0 <= r1 <= info["rows"] and 1 <= c0 <= c1 <= info["columns"]):
            raise ValueError("Границы должны задавать непустой диапазон внутри исходной таблицы")
        prepared.append((block_id, original, info, bounds))
    for block_id, original, info, bounds in prepared:
        value.setdefault("table_originals", {}).setdefault(block_id, deepcopy(original))
        value.setdefault("table_ranges", {})[block_id] = bounds
        r0, r1, c0, c1 = bounds
        result = deepcopy(original)
        if bounds != [1, info["rows"], 1, info["columns"]]:
            result["rows"] = result["rows"][r0 - 1:r1]
            for row in result["rows"]:
                row["cells"] = row["cells"][c0 - 1:c1]
            boxes = [info["boxes"][r * info["columns"] + c] for r in range(r0 - 1, r1) for c in range(c0 - 1, c1)]
            bbox = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
            result["box"] = {"x": bbox[0], "y": bbox[1], "width": bbox[2] - bbox[0], "height": bbox[3] - bbox[1], "rotation": 0}
            result["properties"]["pdf"].update(bbox=bbox, cell_bboxes=boxes, row_count=r1 - r0 + 1,
                column_count_table=c1 - c0 + 1, rows=[row[c0 - 1:c1] for row in info["cells"][r0 - 1:r1]])
        blocks[block_id].clear()
        blocks[block_id].update(result)
