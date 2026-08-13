"""Cross-platform perceptual comparison for rendered document pages."""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageOps


@dataclass(frozen=True)
class PerceptualThresholds:
    min_similarity: float = 0.90
    max_hash_distance: int = 20
    min_foreground_iou: float = 0.30


@dataclass(frozen=True)
class PerceptualComparison:
    similarity: float
    mean_absolute_error: float
    root_mean_square_error: float
    hash_distance: int
    foreground_iou: float

    def passes(self, thresholds: PerceptualThresholds = PerceptualThresholds()) -> bool:
        return (
            self.similarity >= thresholds.min_similarity
            and self.hash_distance <= thresholds.max_hash_distance
            and self.foreground_iou >= thresholds.min_foreground_iou
        )


def difference_heatmap(
    reference: Image.Image | str | Path,
    candidate: Image.Image | str | Path,
) -> tuple[Image.Image, PerceptualComparison]:
    """Create a source/result overlay with red heat proportional to pixel differences."""
    reference_image = _open_image(reference).convert("RGB")
    candidate_image = _open_image(candidate).convert("RGB")
    if candidate_image.size != reference_image.size:
        candidate_image = ImageOps.contain(candidate_image, reference_image.size, method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", reference_image.size, "white")
        offset = (
            (canvas.width - candidate_image.width) // 2,
            (canvas.height - candidate_image.height) // 2,
        )
        canvas.paste(candidate_image, offset)
        candidate_image = canvas
    difference = ImageChops.difference(reference_image, candidate_image).convert("L")
    heat_alpha = difference.point(lambda value: min(220, value * 3))
    overlay = Image.blend(reference_image, candidate_image, 0.35).convert("RGBA")
    heat = Image.new("RGBA", reference_image.size, (220, 38, 38, 0))
    heat.putalpha(heat_alpha)
    overlay.alpha_composite(heat)
    return overlay.convert("RGB"), compare_images(reference_image, candidate_image)


def difference_heatmap_png(reference: bytes, candidate: bytes) -> tuple[bytes, PerceptualComparison]:
    with Image.open(BytesIO(reference)) as left, Image.open(BytesIO(candidate)) as right:
        image, comparison = difference_heatmap(left, right)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue(), comparison


def normalise_image(image: Image.Image, *, size: tuple[int, int] = (160, 160)) -> Image.Image:
    """Нормализовать страницу для устойчивого сравнения между платформами."""

    grayscale = ImageOps.grayscale(image)
    grayscale = ImageOps.autocontrast(grayscale, cutoff=(0.25, 0.05))
    grayscale = grayscale.filter(ImageFilter.GaussianBlur(radius=0.65))
    contained = ImageOps.contain(grayscale, size, method=Image.Resampling.LANCZOS)
    canvas = Image.new("L", size, 255)
    canvas.paste(contained, ((size[0] - contained.width) // 2, (size[1] - contained.height) // 2))
    return canvas


def compare_images(
    reference: Image.Image | str | Path,
    candidate: Image.Image | str | Path,
    *,
    size: tuple[int, int] = (160, 160),
) -> PerceptualComparison:
    """Сравнить страницы после нормализации и вернуть независимые метрики."""

    reference_image = normalise_image(_open_image(reference), size=size)
    candidate_image = normalise_image(_open_image(candidate), size=size)
    difference = ImageChops.difference(reference_image, candidate_image)
    histogram = difference.histogram()
    pixels = size[0] * size[1]
    absolute = sum(value * count for value, count in enumerate(histogram))
    squared = sum((value**2) * count for value, count in enumerate(histogram))
    mae = absolute / (pixels * 255)
    rmse = math.sqrt(squared / pixels) / 255
    reference_hash = _difference_hash(reference_image)
    candidate_hash = _difference_hash(candidate_image)
    return PerceptualComparison(
        similarity=max(0.0, 1.0 - mae),
        mean_absolute_error=mae,
        root_mean_square_error=rmse,
        hash_distance=(reference_hash ^ candidate_hash).bit_count(),
        foreground_iou=_foreground_iou(reference_image, candidate_image),
    )


def render_pdf_pages(path: str | Path, *, dpi: int = 96) -> list[Image.Image]:
    """Рендерить PDF-страницы в RGB Pillow images."""

    import fitz

    pages: list[Image.Image] = []
    with fitz.open(path) as document:
        for page in document:
            pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
            pages.append(Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples))
    return pages


def _open_image(value: Image.Image | str | Path) -> Image.Image:
    if isinstance(value, Image.Image):
        return value.copy()
    with Image.open(value) as image:
        return image.copy()


def _difference_hash(image: Image.Image) -> int:
    sample = image.resize((9, 8), Image.Resampling.LANCZOS)
    pixels = _pixel_values(sample)
    result = 0
    for row in range(8):
        for column in range(8):
            left = pixels[row * 9 + column]
            right = pixels[row * 9 + column + 1]
            result = (result << 1) | int(left > right)
    return result


def _foreground_iou(reference: Image.Image, candidate: Image.Image, *, threshold: int = 246) -> float:
    reference_pixels = _pixel_values(reference)
    candidate_pixels = _pixel_values(candidate)
    intersection = 0
    union = 0
    for left, right in zip(reference_pixels, candidate_pixels, strict=True):
        left_foreground = left < threshold
        right_foreground = right < threshold
        intersection += int(left_foreground and right_foreground)
        union += int(left_foreground or right_foreground)
    return intersection / union if union else 1.0


def _pixel_values(image: Image.Image) -> list[int]:
    flattened = getattr(image, "get_flattened_data", None)
    return list(flattened() if flattened is not None else image.getdata())


__all__ = [
    "PerceptualComparison",
    "PerceptualThresholds",
    "compare_images",
    "difference_heatmap",
    "difference_heatmap_png",
    "normalise_image",
    "render_pdf_pages",
]
