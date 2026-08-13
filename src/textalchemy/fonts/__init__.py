"""Детерминированное разрешение, подмена и аудит шрифтов."""

from textalchemy.fonts.resolver import (
    FontFace,
    FontResolution,
    FontResolutionReport,
    FontResolver,
    prepare_document_fonts,
)

__all__ = ["FontFace", "FontResolution", "FontResolutionReport", "FontResolver", "prepare_document_fonts"]
