"""Target-specific diagnostics for canonical color metadata."""

from __future__ import annotations

from collections.abc import Iterator

from textalchemy.core.color import ColorValue
from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import Block, DocumentModel, Paragraph, Table, TextRun


def preflight_colors(document: DocumentModel, report: ConversionReport, *, target: str) -> None:
    """Report color metadata that the selected writer cannot faithfully apply."""
    supports_blend = target == "html"
    seen: set[tuple[str, str]] = set()
    for location, color in _document_colors(document):
        if color.icc_profile and ("icc", color.icc_profile) not in seen:
            seen.add(("icc", color.icc_profile))
            report.add(
                IssueSeverity.LOSS,
                "color-icc",
                f"{target.upper()} export converts ICC color {color.icc_profile!r} to sRGB",
                location,
            )
        if color.blend_mode != "normal" and not supports_blend and ("blend", color.blend_mode) not in seen:
            seen.add(("blend", color.blend_mode))
            report.add(
                IssueSeverity.LOSS,
                "color-blend",
                f"{target.upper()} export cannot guarantee blend mode {color.blend_mode!r}",
                location,
            )


def _document_colors(document: DocumentModel) -> Iterator[tuple[str, ColorValue]]:
    for style_id, style in document.styles.items():
        for field in ("color", "background"):
            value = getattr(style, field)
            if isinstance(value, ColorValue):
                yield f"styles[{style_id!r}].{field}", value
    for section_index, section in enumerate(document.sections):
        for collection_name in (
            "blocks",
            "headers",
            "footers",
            "first_page_headers",
            "first_page_footers",
            "even_page_headers",
            "even_page_footers",
        ):
            blocks = getattr(section, collection_name)
            yield from _block_colors(blocks, f"sections[{section_index}].{collection_name}")


def _block_colors(blocks: list[Block], location: str) -> Iterator[tuple[str, ColorValue]]:
    for block_index, block in enumerate(blocks):
        block_location = f"{location}[{block_index}]"
        if isinstance(block, Paragraph):
            for inline_index, item in enumerate(block.content):
                if isinstance(item, TextRun):
                    for field in ("color", "background"):
                        value = getattr(item.style, field)
                        if isinstance(value, ColorValue):
                            yield f"{block_location}.content[{inline_index}].style.{field}", value
        elif isinstance(block, Table):
            for row_index, row in enumerate(block.rows):
                for cell_index, cell in enumerate(row.cells):
                    yield from _block_colors(
                        cell.blocks,
                        f"{block_location}.rows[{row_index}].cells[{cell_index}].blocks",
                    )


__all__ = ["preflight_colors"]
