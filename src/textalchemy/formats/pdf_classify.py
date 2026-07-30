"""Семантическая классификация геометрических блоков PDF."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass

from textalchemy.core.types import BlockType
from textalchemy.formats.pdf_geometry import PdfGeometryDocument, PdfPageGeometry, PdfTextBlockGeometry

_CAPTION_RE = re.compile(
    r"^\s*(?:fig(?:ure)?\.?|table|рис(?:унок)?\.?|табл(?:ица)?\.?|схема|диаграмма)\s*[-–—:]?\s*\d+[\d.]*",
    re.IGNORECASE,
)
_PAGE_NUMBER_RE = re.compile(r"\b\d+\b")
_SPACE_RE = re.compile(r"\s+")
_MATH_CHARS = frozenset("=+−-×÷±∓∫∑∏√≤≥≈≠∞^_²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉∂∆∇")


@dataclass(frozen=True)
class PdfSemanticClassification:
    block_type: BlockType = BlockType.PARAGRAPH
    role: str | None = None
    confidence: float = 0.5
    evidence: tuple[str, ...] = ()


def repeated_margin_roles(document: PdfGeometryDocument) -> dict[tuple[int, int], str]:
    """Найти повторяющиеся header/footer blocks с нормализацией номеров страниц."""

    if len(document.pages) < 2:
        return {}
    occurrences: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for page in document.pages:
        for block in page.text_blocks:
            role = _margin_role(block, page)
            normalized = _normalized_repeated_text(block.text)
            if role is not None and normalized:
                occurrences[(role, normalized)].append((page.number, block.number))
    required_pages = max(2, math.ceil(len(document.pages) * 0.5))
    roles: dict[tuple[int, int], str] = {}
    for (role, _), locations in occurrences.items():
        if len({page for page, _ in locations}) >= required_pages:
            roles.update({location: role for location in locations})
    return roles


def classify_text_block(
    block: PdfTextBlockGeometry,
    page: PdfPageGeometry,
    *,
    repeated_role: str | None = None,
) -> PdfSemanticClassification:
    """Классифицировать paragraph/caption/equation/running content."""

    text = block.text.strip()
    if repeated_role is not None:
        return PdfSemanticClassification(
            role=repeated_role,
            confidence=0.98,
            evidence=("repeated-margin-text", "normalized-page-number"),
        )
    if _CAPTION_RE.match(text):
        target = _nearest_caption_target(block, page)
        evidence = ("caption-prefix", f"near-{target}") if target is not None else ("caption-prefix",)
        return PdfSemanticClassification(BlockType.CAPTION, "caption", 0.96, evidence)
    formula_score, evidence = _formula_score(block)
    if formula_score >= 0.65:
        return PdfSemanticClassification(BlockType.EQUATION, "formula", formula_score, tuple(evidence))
    return PdfSemanticClassification()


def _margin_role(block: PdfTextBlockGeometry, page: PdfPageGeometry) -> str | None:
    if block.bbox[3] <= page.height * 0.12:
        return "header"
    if block.bbox[1] >= page.height * 0.88:
        return "footer"
    return None


def _normalized_repeated_text(text: str) -> str:
    normalized = _SPACE_RE.sub(" ", text).strip().casefold()
    return _PAGE_NUMBER_RE.sub("#", normalized)


def _formula_score(block: PdfTextBlockGeometry) -> tuple[float, list[str]]:
    text = block.text.strip()
    if not text or len(text) > 240 or len(block.lines) > 3:
        return 0.0, []
    math_count = sum(character in _MATH_CHARS for character in text)
    alphanumeric = sum(character.isalnum() for character in text)
    math_fonts = {
        span.font.casefold()
        for line in block.lines
        for span in line.spans
        if any(marker in span.font.casefold() for marker in ("math", "symbol", "stix", "cmr", "cmsy"))
    }
    evidence: list[str] = []
    score = 0.0
    if "=" in text:
        score += 0.45
        evidence.append("equality")
    if any(character in text for character in "∫∑∏√∞"):
        score += 0.35
        evidence.append("math-operator")
    if math_count >= 2 and math_count / max(alphanumeric, 1) >= 0.08:
        score += 0.25
        evidence.append("symbol-density")
    if math_fonts:
        score += 0.35
        evidence.append("math-font")
    if len(text) <= 120:
        score += 0.05
    return min(score, 1.0), evidence


def _nearest_caption_target(block: PdfTextBlockGeometry, page: PdfPageGeometry) -> str | None:
    candidates = [
        *(('image', index, image.bbox) for index, image in enumerate(page.image_blocks)),
        *(("table", index, table.bbox) for index, table in enumerate(page.tables)),
    ]
    nearest: tuple[float, str] | None = None
    for kind, index, bbox in candidates:
        if _horizontal_overlap(block.bbox, bbox) < 0.25:
            continue
        distance = min(abs(block.bbox[1] - bbox[3]), abs(bbox[1] - block.bbox[3]))
        if distance <= 72 and (nearest is None or distance < nearest[0]):
            nearest = distance, f"{kind}-{index}"
    return nearest[1] if nearest is not None else None


def _horizontal_overlap(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    intersection = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    minimum_width = min(max(0.0, left[2] - left[0]), max(0.0, right[2] - right[0]))
    return intersection / minimum_width if minimum_width else 0.0


__all__ = ["PdfSemanticClassification", "classify_text_block", "repeated_margin_roles"]
