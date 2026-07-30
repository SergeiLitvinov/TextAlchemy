"""Метрики качества и визуальной регрессии документов."""

from textalchemy.quality.visual import (
    PerceptualComparison,
    PerceptualThresholds,
    compare_images,
    normalise_image,
    render_pdf_pages,
)

__all__ = [
    "PerceptualComparison",
    "PerceptualThresholds",
    "compare_images",
    "normalise_image",
    "render_pdf_pages",
]
