"""Own PDF geometry acceptance through the application executor."""

from io import BytesIO

import pymupdf
import pytest
from opendoc_model import get_integration, get_page_geometry, load_document
from PIL import Image, ImageDraw

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.types import DocFormat


def native_snapshot(path):
    with pymupdf.open(path) as pdf:
        page = pdf[0]
        pixels = page.get_pixmap(alpha=False)
        return (tuple(page.mediabox), tuple(page.cropbox), page.rotation,
                pixels.width, pixels.height, pixels.samples)


@pytest.mark.parametrize("origin", [(0, 0), (20, 30), (-30, -40)])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_media_crop_rotation_and_pixels_survive_two_cycles(tmp_path, origin, rotation):
    image = Image.new("RGB", (120, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((5, 5, 114, 154), outline="red", width=4)
    draw.line((10, 20, 100, 140), fill="blue", width=5)
    stream = BytesIO()
    image.save(stream, format="PNG")
    source = tmp_path / "own.pdf"
    ox, oy = origin
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.set_mediabox(pymupdf.Rect(ox, oy, ox + 595, oy + 842))
        page.insert_image(pymupdf.Rect(0, 0, 595, 842), stream=stream.getvalue())
        page.set_cropbox(pymupdf.Rect(ox + 50, 70, ox + 545, 772))
        page.set_rotation(rotation)
        pdf.save(source)
    original = source.read_bytes()
    expected = native_snapshot(source)
    current = source
    executor = ConversionExecutor()
    for cycle in range(2):
        model_path = tmp_path / f"cycle-{cycle}.json"
        output = tmp_path / f"cycle-{cycle}.pdf"
        report = executor.execute(ConversionRequest(current, model_path, DocFormat.PDF, DocFormat.MODEL))
        assert report.success, report.issues
        page = get_integration(load_document(model_path)).pages[0]
        geometry = get_page_geometry(page)
        assert geometry is not None
        assert (page.width, page.height) == (595, 842)
        assert (geometry.media_box.x, geometry.media_box.y,
                geometry.media_box.width, geometry.media_box.height) == (ox, -(oy + 842), 595, 842)
        assert geometry.crop_box is not None
        assert geometry.rotation == rotation
        report = executor.execute(ConversionRequest(model_path, output, DocFormat.MODEL, DocFormat.PDF))
        assert report.success, report.issues
        assert native_snapshot(output) == expected
        current = output
    assert source.read_bytes() == original
