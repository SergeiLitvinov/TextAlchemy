"""Объединение текстового слоя PDF и OCR с координатами и уверенностью.

Стратегия:
  Для каждой страницы:
  1. Оценить покрытие текстового слоя (суммарная длина текста в text_blocks).
  2. Если покрытие достаточное (> 200 символов) — используем text layer,
     но добавляем OCR-блоки в областях, где text layer пуст.
  3. Если покрытия нет — используем только OCR.
  4. Итоговый ``Text`` содержит блоки с полями ``confidence`` и ``source``
     в ``meta``.

Этот модуль — надстройка над ``PdfGeometryDocument`` (из pdf_geometry.py)
и ``OcrPageResult`` (из pdf_ocr_types.py). Не требует ни одного из трёх
OCR-бэкендов — если их нет, просто возвращает семантический ``Text`` без
OCR-данных.
"""

from __future__ import annotations

from typing import Any

from textalchemy.core.types import Block, BlockType, DocFormat, Table, Text
from textalchemy.formats.pdf_classify import classify_text_block, repeated_margin_roles
from textalchemy.formats.pdf_geometry import PdfGeometryDocument, PdfTableGeometry, PdfTextBlockGeometry
from textalchemy.formats.pdf_layout import analyze_reading_order
from textalchemy.formats.pdf_ocr_types import MergedTextBlock, OcrPageResult

# Минимальная длина текста на странице, при которой text layer считается достаточным.
_TEXT_LAYER_MIN_CHARS = 200

# Доля площади страницы, занимаемая текстовыми блоками.
_TEXT_LAYER_MIN_COVERAGE = 0.02


def _page_text_coverage(page_text: str, page_width: float, page_height: float) -> float:
    """Оценить долю площади страницы, покрытой текстом (грубо)."""
    if page_width <= 0 or page_height <= 0:
        return 0.0
    char_count = len(page_text.strip())
    area = page_width * page_height
    return char_count / area if area > 0 else 0.0


def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _bbox_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """Intersection-over-union of two bboxes."""
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    a_area = _bbox_area(a)
    b_area = _bbox_area(b)
    union = a_area + b_area - intersection
    return intersection / union if union > 0 else 0.0


def _merge_text_layer_and_ocr_page(
    text_blocks: list[PdfTextBlockGeometry],
    tables: list[PdfTableGeometry],
    ocr_page: OcrPageResult,
    page_number: int,
    page_width: float,
    page_height: float,
) -> list[MergedTextBlock]:
    """Merge text layer and OCR blocks for a single page."""
    merged: list[MergedTextBlock] = []

    # Collect text layer blocks (non-table)
    tl_text = " ".join(b.text for b in text_blocks)
    tl_coverage = _page_text_coverage(tl_text, page_width, page_height)
    has_good_text_layer = len(tl_text.strip()) >= _TEXT_LAYER_MIN_CHARS and tl_coverage >= _TEXT_LAYER_MIN_COVERAGE

    # Mark OCR blocks that overlap significantly with text layer blocks
    ocr_used = [False] * len(ocr_page.blocks)

    # Add text layer blocks
    for block in text_blocks:
        if not block.text.strip():
            continue
        merged.append(
            MergedTextBlock(
                text=block.text,
                bbox=block.bbox,
                confidence=0.95 if has_good_text_layer else 0.5,
                source="text_layer",
                page=page_number,
                properties={
                    "source_block": block.number,
                    "font_spans": [
                        {"font": s.font, "size": s.size, "flags": s.flags} for line in block.lines for s in line.spans
                    ],
                },
            )
        )

    # Add OCR blocks that don't overlap significantly with text layer
    if not has_good_text_layer:
        for idx, ocr_block in enumerate(ocr_page.blocks):
            if not ocr_block.text.strip():
                continue
            # Check overlap with existing text layer blocks
            overlaps_text = any(_bbox_overlap(ocr_block.bbox, existing.bbox) > 0.3 for existing in merged)
            if not overlaps_text:
                ocr_used[idx] = True
                merged.append(
                    MergedTextBlock(
                        text=ocr_block.text,
                        bbox=ocr_block.bbox,
                        confidence=ocr_block.confidence,
                        source="ocr",
                        page=page_number,
                    )
                )

    # Sort by vertical position then horizontal
    merged.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
    return merged


def _compute_overall_confidence(blocks: list[MergedTextBlock]) -> float:
    if not blocks:
        return 0.0
    return sum(b.confidence for b in blocks) / len(blocks)


def merge_pdf_with_ocr(
    geometry: PdfGeometryDocument,
    ocr_pages: list[OcrPageResult] | None = None,
) -> Text:
    """Merge PDF geometry text layer with optional OCR results.

    Args:
        geometry: Geometry document from ``extract_pdf_geometry()``.
        ocr_pages: Per-page OCR results from ``OcrEngine.recognize_pdf_geometry()``.
            If None, falls back to pure text layer (geometry-only).

    Returns:
        A ``Text`` with per-block ``confidence``, ``source`` and ``bbox`` in meta.
    """
    all_blocks: list[Block] = []
    all_tables: list[Table] = []
    plain_parts: list[str] = []
    margin_roles = repeated_margin_roles(geometry)

    for page_index, page in enumerate(geometry.pages):
        page_number = page_index + 1
        ocr_page = ocr_pages[page_index] if ocr_pages and page_index < len(ocr_pages) else None

        # Separate text and table blocks
        text_blocks = list(page.text_blocks)
        tables = list(page.tables)

        # Compute reading order from text blocks + tables
        layout = analyze_reading_order([*text_blocks, *tables], page.width)

        if ocr_page and ocr_page.blocks:
            # Merge text layer + OCR
            merged_blocks = _merge_text_layer_and_ocr_page(
                text_blocks,
                tables,
                ocr_page,
                page_number,
                page.width,
                page.height,
            )
            for mb in merged_blocks:
                block_type = BlockType.PARAGRAPH
                meta: dict[str, Any] = {
                    "bbox": list(mb.bbox),
                    "confidence": round(mb.confidence, 4),
                    "source": mb.source,
                    "page_width": page.width,
                    "page_height": page.height,
                }
                meta.update(mb.properties)
                all_blocks.append(
                    Block(
                        type=block_type,
                        text=mb.text,
                        page=page_number,
                        meta=meta,
                    )
                )
                if not meta.get("excluded_from_plain"):
                    plain_parts.append(mb.text)
        else:
            # Pure text layer (no OCR)
            for reading_index, ordered_block in enumerate(layout.blocks):
                source = ordered_block.block
                text = source.text
                if not text.strip():
                    continue

                meta: dict[str, Any] = {
                    "bbox": list(source.bbox),
                    "reading_order": reading_index,
                    "column": ordered_block.column,
                    "column_count": layout.column_count,
                    "spanning": ordered_block.spanning,
                    "gutter": list(layout.gutter) if layout.gutter is not None else None,
                    "page_width": page.width,
                    "page_height": page.height,
                    "confidence": 1.0,
                    "source": "text_layer",
                }

                if isinstance(source, PdfTableGeometry):
                    rows = [list(row) for row in source.rows]
                    meta.update(
                        {
                            "rows": rows,
                            "source_table": source.number,
                            "row_count": source.row_count,
                            "column_count_table": source.column_count,
                            "table_strategy": source.strategy,
                            "cell_bboxes": [list(cell.bbox) if cell.bbox is not None else None for cell in source.cells],
                        }
                    )
                    all_blocks.append(Block(type=BlockType.TABLE, text=text, page=page_number, meta=meta))
                    all_tables.append(Table(rows=rows, page=page_number))
                else:
                    meta["source_block"] = source.number
                    classification = classify_text_block(
                        source,
                        page,
                        repeated_role=margin_roles.get((page_number, source.number)),
                    )
                    meta.update(
                        {
                            "semantic_role": classification.role,
                            "semantic_confidence": classification.confidence,
                            "semantic_evidence": list(classification.evidence),
                        }
                    )
                    if classification.role in {"header", "footer"}:
                        meta["excluded_from_plain"] = True
                    all_blocks.append(
                        Block(
                            type=classification.block_type,
                            text=text,
                            page=page_number,
                            meta=meta,
                        )
                    )

                if not meta.get("excluded_from_plain"):
                    plain_parts.append(text)

    return Text(
        blocks=all_blocks,
        tables=all_tables,
        plain="\n".join(plain_parts),
        source_format=DocFormat.PDF,
        engine=geometry.engine + "+ocr" if ocr_pages else geometry.engine,
        pages=len(geometry.pages),
        warnings=list(geometry.warnings) + ([w for p in ocr_pages for w in p.warnings] if ocr_pages else []),
    )


def read_pdf_with_ocr(
    path: str,
    ocr_engine: Any = None,
    scale: int = 3,
    handwriting: bool = False,
) -> Text:
    """Read a PDF, merging text layer with OCR if an OCR engine is available.

    This is the main entry point for the combined pipeline. It:
    1. Extracts PDF geometry (text blocks, tables, images metadata)
    2. Optionally runs OCR with bounding boxes
    3. Merges both sources into a single ``Text`` with per-block confidence

    Args:
        path: Path to the PDF file.
        ocr_engine: An ``OcrEngine`` instance, or None to skip OCR.
        scale: Rendering scale for OCR (2-6).
        handwriting: Enable handwriting-optimised OCR mode.

    Returns:
        ``Text`` with merged content.
    """
    from textalchemy.formats.pdf import extract_pdf_geometry as _extract_geometry

    geometry = _extract_geometry(path)

    ocr_pages: list[OcrPageResult] | None = None
    if ocr_engine is not None and ocr_engine.is_available:
        try:
            ocr_pages = ocr_engine.recognize_pdf_geometry(path, scale=scale, handwriting=handwriting)
        except Exception as exc:  # noqa: BLE001
            geometry.warnings.append(f"OCR failed: {exc}")

    return merge_pdf_with_ocr(geometry, ocr_pages)


__all__ = [
    "MergedTextBlock",
    "merge_pdf_with_ocr",
    "read_pdf_with_ocr",
]
