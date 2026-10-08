"""Own full-page raster acceptance through two published-adapter cycles."""

import io

import pymupdf
from PIL import Image, ImageDraw

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.types import DocFormat
from tools.acceptance.scans import compare_pdf


def scan_pdf(path):
    image = Image.new("RGB", (595, 842), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 594, 841), outline="red", width=12)
    draw.line((30, 40, 500, 700), fill="blue", width=8)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    with pymupdf.open() as pdf:
        for _ in range(2):
            page = pdf.new_page(width=595, height=842)
            page.insert_image(page.rect, stream=buffer.getvalue())
        pdf.save(path)
    return path


def test_full_page_scan_two_cycles_preserve_geometry_and_pixels(tmp_path):
    source = scan_pdf(tmp_path / "source.pdf")
    original = source.read_bytes()
    executor = ConversionExecutor()
    current = source
    for cycle in (1, 2):
        model = tmp_path / f"cycle-{cycle}.json"
        imported = executor.execute(ConversionRequest(current, model, DocFormat.PDF, DocFormat.MODEL))
        assert imported.success, imported.to_dict()
        assert imported.metrics["executed_steps"] == ["pdf.model"]
        result = tmp_path / f"cycle-{cycle}.pdf"
        exported = executor.execute(ConversionRequest(
            model, result, DocFormat.MODEL, DocFormat.PDF, quality_policy=QualityPolicy(0)))
        assert exported.success, exported.to_dict()
        evidence = compare_pdf(source, result)
        assert evidence["page_count_equal"] and len(evidence["pages"]) == 2
        assert evidence["full_visual_acceptance"] is None
        for measured in evidence["pages"]:
            assert measured["page_size_equal"]
            assert measured["source_text_empty"] and measured["result_text_empty"]
            assert measured["source_image_boxes"] == measured["result_image_boxes"]
            assert measured["pixel_bytes_equal"] and measured["mae_normalized"] == 0
        assert not any(issue.severity.value == "loss" for issue in exported.issues)
        current = result
    assert source.read_bytes() == original
