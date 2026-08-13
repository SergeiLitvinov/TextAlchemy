"""Unit-тесты переносимых perceptual visual metrics."""

from PIL import Image, ImageDraw

from textalchemy.quality.visual import PerceptualThresholds, compare_images, difference_heatmap, normalise_image


def _layout_image(offset: int = 0):
    image = Image.new("RGB", (480, 640), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40 + offset, 35, 440 + offset, 75), fill="#2E74B5")
    for y in range(115, 310, 28):
        draw.rectangle((45 + offset, y, 205 + offset, y + 8), fill="#333333")
        draw.rectangle((275 + offset, y, 435 + offset, y + 8), fill="#333333")
    draw.rectangle((45 + offset, 350, 435 + offset, 500), outline="#2E74B5", width=4)
    return image


def test_normalise_image_preserves_page_aspect_on_fixed_canvas():
    normalized = normalise_image(_layout_image(), size=(160, 160))

    assert normalized.mode == "L"
    assert normalized.size == (160, 160)
    assert normalized.getbbox() == (0, 0, 160, 160)


def test_perceptual_comparison_tolerates_small_rasterisation_shift():
    comparison = compare_images(_layout_image(), _layout_image(offset=1))

    assert comparison.passes(PerceptualThresholds(min_similarity=0.97, max_hash_distance=8, min_foreground_iou=0.75))


def test_perceptual_comparison_rejects_missing_page_content():
    comparison = compare_images(_layout_image(), Image.new("RGB", (480, 640), "white"))

    assert comparison.passes() is False
    assert comparison.foreground_iou == 0


def test_difference_heatmap_marks_changed_pixels_and_returns_metrics():
    reference = _layout_image()
    candidate = _layout_image(offset=8)

    heatmap, comparison = difference_heatmap(reference, candidate)

    assert heatmap.mode == "RGB"
    assert heatmap.size == reference.size
    assert comparison.similarity < 1
    pixels = heatmap.get_flattened_data()
    red_pixels = sum(1 for red, green, blue in pixels if red > green * 1.2 and red > blue * 1.2)
    assert red_pixels > 0
