"""Shared font usage collection and deterministic OpenType subsetting."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from textalchemy.core.document_model import Block, DocumentModel, Paragraph, Table, TextRun


@dataclass(frozen=True)
class FontUsage:
    family: str
    path: Path
    bold: bool
    italic: bool
    characters: frozenset[str]
    embeddable: bool
    subsettable: bool


def collect_font_usages(document: DocumentModel) -> list[FontUsage]:
    usages: dict[tuple[str, str, bool, bool], set[str]] = {}
    embeddable: dict[tuple[str, str, bool, bool], bool] = {}
    subsettable: dict[tuple[str, str, bool, bool], bool] = {}

    def collect(blocks: list[Block]) -> None:
        for block in blocks:
            if isinstance(block, Paragraph):
                for item in block.content:
                    if not isinstance(item, TextRun):
                        continue
                    resolution = item.style.properties.get("font_resolution")
                    if not isinstance(resolution, dict) or not resolution.get("path"):
                        continue
                    key = (
                        str(resolution.get("resolved") or item.style.font_family or "Font"),
                        str(resolution["path"]),
                        bool(item.style.bold),
                        bool(item.style.italic),
                    )
                    usages.setdefault(key, set()).update(item.text)
                    embeddable[key] = bool(resolution.get("embeddable", False))
                    subsettable[key] = bool(resolution.get("subsettable", True))
            elif isinstance(block, Table):
                for row in block.rows:
                    for cell in row.cells:
                        collect(cell.blocks)

    for section in document.sections:
        for blocks in (
            section.blocks,
            section.headers,
            section.footers,
            section.first_page_headers,
            section.first_page_footers,
            section.even_page_headers,
            section.even_page_footers,
        ):
            collect(blocks)
    return [
        FontUsage(family, Path(path), bold, italic, frozenset(characters), embeddable[key], subsettable[key])
        for key, characters in sorted(usages.items())
        for family, path, bold, italic in (key,)
    ]


def subset_font(usage: FontUsage) -> bytes:
    """Return a deterministic glyph subset, falling back to the full font if unsupported."""
    source = usage.path.read_bytes()
    if not usage.characters or not usage.subsettable:
        return source
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont

        font = TTFont(BytesIO(source), recalcTimestamp=False)
        options = subset.Options()
        options.recalc_timestamp = False
        options.canonical_order = True
        options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 16, 17]
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(text="".join(sorted(usage.characters)))
        subsetter.subset(font)
        output = BytesIO()
        font.save(output, reorderTables=True)
        font.close()
        return output.getvalue()
    except Exception:  # noqa: BLE001 - unsupported fonts remain embeddable without subsetting
        return source


__all__ = ["FontUsage", "collect_font_usages", "subset_font"]
