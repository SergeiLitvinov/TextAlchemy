"""Подготовка геометрии отображаемых объектов для браузерного HTML."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from textalchemy.convert.stages import StageContext, StageKind, StageResult, StageValue
from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import Box, DocumentModel, Image, Paragraph, Table
from textalchemy.core.units import points_to_css_px


class _CancelledError(Exception):
    pass


@dataclass(frozen=True)
class HtmlLayoutStage:
    """Рассчитать CSS-геометрию без изменения исходных координат модели."""

    id: str = "html.layout"
    kind: StageKind = StageKind.LAYOUT

    def execute(self, value: StageValue, context: StageContext) -> StageResult:
        if not isinstance(value, DocumentModel):
            raise TypeError("HTML layout requires DocumentModel")
        report = ConversionReport(context.output_path)
        counts = {"positioned_blocks": 0, "origin_blocks": 0, "affine_objects": 0, "inline_images": 0}

        def prepare(node, *, positioned):
            if context.cancelled():
                raise _CancelledError
            affine = _pptx_affine(node.properties) if positioned else None
            counts["affine_objects"] += affine is not None
            counts["inline_images"] += isinstance(node, Image) and not positioned
            counts["positioned_blocks"] += positioned and (node.box is not None or affine is not None)
            counts["origin_blocks"] += positioned and node.box is not None and not (node.box.x or node.box.y)
            styles = geometry_styles(node.box, node.properties, positioned=positioned, browser=True)
            return replace(node, properties={**node.properties, "html_layout": {"styles": styles}})

        def blocks(items):
            result = []
            for node in items:
                if isinstance(node, Paragraph):
                    node = replace(
                        node,
                        content=[prepare(item, positioned=False) if isinstance(item, Image) else item for item in node.content],
                    )
                    node = prepare(node, positioned=True)
                elif isinstance(node, Table):
                    node = replace(
                        node,
                        rows=[
                            replace(row, cells=[replace(cell, blocks=blocks(cell.blocks)) for cell in row.cells])
                            for row in node.rows
                        ],
                    )
                    node = prepare(node, positioned=True)
                elif isinstance(node, Image):
                    node = prepare(node, positioned=True)
                result.append(node)
            return result

        try:
            if context.cancelled():
                raise _CancelledError
            sections = [
                replace(section, blocks=blocks(section.blocks), headers=blocks(section.headers), footers=blocks(section.footers))
                for section in value.sections
            ]
        except _CancelledError:
            report.add(IssueSeverity.ERROR, "cancelled", "HTML layout preparation cancelled")
            return StageResult(value, report)
        report.metrics["html_layout"] = {"stage": self.id, **counts}
        return StageResult(replace(value, sections=sections), report)


def geometry_styles(box: Box | None, properties: Any, *, positioned: bool, browser: bool = False) -> list[str]:
    """CSS-геометрия; браузер требует пиксели для переноса affine-матрицы."""
    affine = _pptx_affine(properties) if positioned else None
    if affine is not None:
        matrix, width, height = affine
        a, b, c, d, e, f = matrix
        if browser:
            e, f = points_to_css_px(e), points_to_css_px(f)
        return [
            f"width:{width:g}pt",
            f"height:{height:g}pt",
            "position:absolute",
            "left:0pt",
            "top:0pt",
            f"transform:matrix({a:g},{b:g},{c:g},{d:g},{e:g},{f:g})",
            "transform-origin:0 0",
        ]
    if box is None:
        return []
    values = []
    if box.width > 0:
        values.append(f"width:{box.width:g}pt")
    if box.height > 0:
        values.append(f"height:{box.height:g}pt")
    if positioned and (browser or box.x or box.y):
        values.extend(("position:absolute", f"left:{box.x:g}pt", f"top:{box.y:g}pt"))
    if box.rotation:
        values.extend((f"transform:rotate({box.rotation:g}deg)", "transform-origin:center"))
    return values


def _pptx_affine(properties: Any) -> tuple[list[float], float, float] | None:
    if not hasattr(properties, "get"):
        return None
    pptx = properties.get("pptx")
    transform = pptx.get("transform") if isinstance(pptx, dict) else None
    if not isinstance(transform, dict):
        return None
    matrix, width, height = transform.get("matrix"), transform.get("width_pt"), transform.get("height_pt")
    if not isinstance(matrix, list) or len(matrix) != 6:
        return None
    values = [float(value) for value in matrix if isinstance(value, (int, float))]
    if len(values) != 6 or not all(math.isfinite(value) for value in values):
        return None
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)) or width <= 0 or height <= 0:
        return None
    return values, float(width), float(height)
