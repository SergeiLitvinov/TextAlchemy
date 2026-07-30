"""Cross-platform perceptual regression against committed page images."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from tests.corpus.multiformat import build_multiformat_corpus
from textalchemy.quality.visual import PerceptualThresholds, compare_images, render_pdf_pages

VISUAL_DIR = Path(__file__).parents[1] / "corpus" / "visual"
MANIFEST = json.loads((VISUAL_DIR / "manifest.json").read_text(encoding="utf-8"))


def test_committed_visual_references_match_manifest():
    for page in MANIFEST["pages"]:
        reference = VISUAL_DIR / page["file"]
        with Image.open(reference) as image:
            assert image.size == (page["width"], page["height"])
        assert hashlib.sha256(reference.read_bytes()).hexdigest() == page["sha256"]


def test_pdf_corpus_matches_perceptual_page_references(tmp_path):
    pdf = build_multiformat_corpus(tmp_path)["pdf"]
    rendered_pages = render_pdf_pages(pdf, dpi=MANIFEST["dpi"])
    thresholds = PerceptualThresholds(**MANIFEST["thresholds"])

    assert len(rendered_pages) == len(MANIFEST["pages"])
    for index, (rendered, expected) in enumerate(zip(rendered_pages, MANIFEST["pages"], strict=True), start=1):
        comparison = compare_images(
            VISUAL_DIR / expected["file"],
            rendered,
            size=tuple(MANIFEST["normalised_size"]),
        )
        assert comparison.passes(thresholds), f"page {index}: {comparison}"
