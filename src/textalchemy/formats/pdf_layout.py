"""Детерминированный порядок чтения для геометрических блоков PDF."""

from __future__ import annotations

from dataclasses import dataclass

from textalchemy.formats.pdf_geometry import PdfPageGeometry, PdfTableGeometry, PdfTextBlockGeometry

PdfPositionedBlock = PdfTextBlockGeometry | PdfTableGeometry


@dataclass(frozen=True)
class PdfOrderedBlock:
    block: PdfPositionedBlock
    column: int | None = None
    spanning: bool = False


@dataclass(frozen=True)
class PdfPageReadingOrder:
    blocks: tuple[PdfOrderedBlock, ...]
    column_count: int = 1
    gutter: tuple[float, float] | None = None


def analyze_page_reading_order(page: PdfPageGeometry) -> PdfPageReadingOrder:
    """Упорядочить блоки страницы, распознав распространённую двухколоночную схему."""

    return analyze_reading_order([block for block in page.text_blocks if block.text.strip()], page.width)


def analyze_reading_order(blocks: list[PdfPositionedBlock], page_width: float) -> PdfPageReadingOrder:
    """Упорядочить произвольные позиционированные text/table blocks."""

    gutter = _detect_two_column_gutter(blocks, page_width)
    if gutter is None:
        ordered = sorted(blocks, key=_geometric_key)
        return PdfPageReadingOrder(tuple(PdfOrderedBlock(block, column=0) for block in ordered))

    gutter_left, gutter_right = gutter
    columns: list[PdfOrderedBlock] = []
    spanning: list[PdfOrderedBlock] = []
    split = (gutter_left + gutter_right) / 2
    for block in blocks:
        x0, _, x1, _ = block.bbox
        if x0 < gutter_left and x1 > gutter_right:
            spanning.append(PdfOrderedBlock(block, spanning=True))
        else:
            center = (x0 + x1) / 2
            columns.append(PdfOrderedBlock(block, column=0 if center < split else 1))

    ordered: list[PdfOrderedBlock] = []
    remaining = columns
    for boundary in sorted(spanning, key=lambda item: _geometric_key(item.block)):
        before = [item for item in remaining if item.block.bbox[1] < boundary.block.bbox[1]]
        ordered.extend(_order_columns(before))
        before_ids = {id(item) for item in before}
        remaining = [item for item in remaining if id(item) not in before_ids]
        ordered.append(boundary)
    ordered.extend(_order_columns(remaining))
    return PdfPageReadingOrder(tuple(ordered), column_count=2, gutter=gutter)


def _detect_two_column_gutter(
    blocks: list[PdfPositionedBlock],
    page_width: float,
) -> tuple[float, float] | None:
    candidates = [block for block in blocks if _width(block) <= page_width * 0.62]
    if len(candidates) < 2:
        return None
    centers = sorted(((_center_x(block), block) for block in candidates), key=lambda item: (item[0], item[1].number))
    gaps = [(centers[index + 1][0] - centers[index][0], index) for index in range(len(centers) - 1)]
    gap, split_index = max(gaps, default=(0.0, 0))
    if gap < max(24.0, page_width * 0.08):
        return None
    left = [item[1] for item in centers[: split_index + 1]]
    right = [item[1] for item in centers[split_index + 1 :]]
    if not left or not right or not _vertically_overlap(left, right):
        return None
    gutter_left = max(block.bbox[2] for block in left)
    gutter_right = min(block.bbox[0] for block in right)
    if gutter_right - gutter_left < max(8.0, page_width * 0.02):
        return None
    return gutter_left, gutter_right


def _vertically_overlap(left: list[PdfPositionedBlock], right: list[PdfPositionedBlock]) -> bool:
    left_top = min(block.bbox[1] for block in left)
    left_bottom = max(block.bbox[3] for block in left)
    right_top = min(block.bbox[1] for block in right)
    right_bottom = max(block.bbox[3] for block in right)
    return min(left_bottom, right_bottom) > max(left_top, right_top)


def _order_columns(items: list[PdfOrderedBlock]) -> list[PdfOrderedBlock]:
    return sorted(items, key=lambda item: (item.column if item.column is not None else -1, *_geometric_key(item.block)))


def _geometric_key(block: PdfPositionedBlock) -> tuple[float, float, int]:
    return block.bbox[1], block.bbox[0], block.number


def _width(block: PdfPositionedBlock) -> float:
    return max(0.0, block.bbox[2] - block.bbox[0])


def _center_x(block: PdfPositionedBlock) -> float:
    return (block.bbox[0] + block.bbox[2]) / 2


__all__ = [
    "PdfOrderedBlock",
    "PdfPageReadingOrder",
    "PdfPositionedBlock",
    "analyze_page_reading_order",
    "analyze_reading_order",
]
