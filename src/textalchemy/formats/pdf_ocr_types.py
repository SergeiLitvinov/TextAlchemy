"""Типы для OCR-блоков с координатами и уверенностью.

Содержит структуры, общие для всех OCR-бэкендов, и позволяющие
объединять текстовый слой PDF с результатами OCR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OcrBlockGeometry:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float = 0.0
    page: int = 1

    def __bool__(self) -> bool:
        return bool(self.text.strip())


@dataclass
class OcrPageResult:
    blocks: list[OcrBlockGeometry] = field(default_factory=list)
    language: str = "rus"
    pages: int = 1
    warnings: list[str] = field(default_factory=list)

    @property
    def plain(self) -> str:
        return "\n".join(block.text for block in self.blocks)

    def __bool__(self) -> bool:
        return bool(self.blocks)


@dataclass
class MergedTextBlock:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float
    source: str  # "text_layer" | "ocr" | "merged"
    page: int = 1
    properties: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "MergedTextBlock",
    "OcrBlockGeometry",
    "OcrPageResult",
]
