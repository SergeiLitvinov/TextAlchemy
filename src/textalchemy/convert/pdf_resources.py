"""Подготовка изображений для PDF Story без изменения исходной модели."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from textalchemy.convert.html_resources import HtmlResourceStage, document_images
from textalchemy.convert.stages import StageContext, StageKind, StageResult, StageValue
from textalchemy.core.diagnostics import IssueSeverity
from textalchemy.core.document_model import DocumentModel, ResourceKind


@dataclass(frozen=True)
class PdfResourceStage:
    """Материализовать ресурсы и заменить используемые SVG снимками PNG для Story."""

    id: str = "pdf.resources"
    kind: StageKind = StageKind.RESOURCES

    def execute(self, value: StageValue, context: StageContext) -> StageResult:
        prepared = HtmlResourceStage(id=self.id).execute(value, context)
        report = prepared.report
        if not report.success:
            return prepared
        document = prepared.value
        assert isinstance(document, DocumentModel) and isinstance(value, DocumentModel)
        resources = dict(document.resources)
        used = {image.resource_id for image, _ in document_images(value)}
        converted = png_bytes = 0
        for key, resource in document.resources.items():
            # Unused attachments must not be decoded or cause conversion losses.
            if key not in used or resource.media_type != "image/svg+xml":
                continue
            if context.cancelled():
                report.add(IssueSeverity.ERROR, "cancelled", "PDF resource preparation cancelled")
                break
            try:
                png = _rasterize_svg(resource.data)
            except Exception as error:  # noqa: BLE001 - optional backend has heterogeneous errors
                report.add(IssueSeverity.ERROR, "image", f"cannot rasterize SVG resource {key!r}: {error}")
                continue
            resources[key] = replace(resource, kind=ResourceKind.RASTER_IMAGE, media_type="image/png", data=png)
            converted += 1
            png_bytes += len(png)
            report.add(
                IssueSeverity.LOSS,
                "image-vector",
                f"SVG resource {key!r} rasterized for the PDF HTML backend; vector editability is lost",
            )
        report.metrics["resource_preparation"].update(
            svg_rasterized=converted,
            png_bytes=png_bytes,
            accepted=report.success,
        )
        return StageResult(replace(document, resources=resources), report)


def _rasterize_svg(raw: bytes) -> bytes:
    import fitz

    with fitz.open(stream=raw, filetype="svg") as vector:
        page = vector[0]
        area = page.rect.width * page.rect.height
        if area <= 0 or not math.isfinite(area):
            raise ValueError("invalid SVG dimensions")
        scale = min(2.0, math.sqrt(16_000_000 / area), 8192 / max(page.rect.width, page.rect.height))
        return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True).tobytes("png")
