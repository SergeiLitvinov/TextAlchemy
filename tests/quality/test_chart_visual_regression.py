"""Визуальная регрессия диаграмм против committed golden PNG.

Диаграммы рендерятся детерминированно: DocumentModel -> PDF (fitz.Story) -> PNG.
Golden-изображения лежат в ``tests/corpus/visual/charts/``; регенерация:
``uv run python -m tests.corpus.charts``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from tests.corpus.charts import write_chart_pdf
from textalchemy.quality.visual import PerceptualThresholds, compare_images, render_pdf_pages

VISUAL_DIR = Path(__file__).parents[1] / "corpus" / "visual" / "charts"
MANIFEST = json.loads((VISUAL_DIR / "manifest.json").read_text(encoding="utf-8"))


def test_committed_chart_references_match_manifest():
    for page in MANIFEST["pages"]:
        reference = VISUAL_DIR / page["file"]
        with Image.open(reference) as image:
            assert image.size == (page["width"], page["height"])
        assert hashlib.sha256(reference.read_bytes()).hexdigest() == page["sha256"]


def test_chart_corpus_matches_perceptual_page_references(tmp_path):
    pdf = write_chart_pdf(tmp_path / "chart-corpus.pdf")
    rendered_pages = render_pdf_pages(pdf, dpi=MANIFEST["dpi"])
    thresholds = PerceptualThresholds(**MANIFEST["thresholds"])

    assert len(rendered_pages) == len(MANIFEST["pages"])
    for rendered, expected in zip(rendered_pages, MANIFEST["pages"], strict=True):
        comparison = compare_images(
            VISUAL_DIR / expected["file"],
            rendered,
            size=tuple(MANIFEST["normalised_size"]),
        )
        assert comparison.passes(thresholds), f"{expected['name']}: {comparison}"
