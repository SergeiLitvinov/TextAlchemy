"""Regeneration helper for committed cross-platform page references."""

from __future__ import annotations

import tempfile
from pathlib import Path

from tests.corpus.multiformat import build_multiformat_corpus
from textalchemy.quality.visual import render_pdf_pages


def build_visual_references(output_dir: str | Path) -> list[Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="textalchemy-visual-corpus-") as temporary:
        pdf = build_multiformat_corpus(Path(temporary))["pdf"]
        pages = render_pdf_pages(pdf, dpi=96)
    outputs: list[Path] = []
    for index, page in enumerate(pages, start=1):
        output = target / f"scientific-layout-page-{index}.png"
        page.save(output, format="PNG", optimize=False, compress_level=9)
        outputs.append(output)
    return outputs


__all__ = ["build_visual_references"]


if __name__ == "__main__":
    for result in build_visual_references(Path("tests/corpus/visual")):
        print(result)
