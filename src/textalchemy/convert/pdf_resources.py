"""Image adaptation for the PDF Story backend without changing source resources."""

import base64
import math
from pathlib import Path

from textalchemy.convert.html_writer import _HtmlRenderer
from textalchemy.core.diagnostics import IssueSeverity


class PdfHtmlRenderer(_HtmlRenderer):
    """Story accepts raster images but does not render SVG image data URIs."""

    def _resource_uri(self, resource):
        if resource.media_type != "image/svg+xml":
            return super()._resource_uri(resource)
        import fitz

        raw = resource.data if resource.data is not None else Path(resource.source).read_bytes()
        try:
            with fitz.open(stream=raw, filetype="svg") as vector:
                page = vector[0]
                area = page.rect.width * page.rect.height
                if area <= 0 or not math.isfinite(area):
                    raise ValueError("invalid SVG dimensions")
                scale = min(2.0, math.sqrt(16_000_000 / area), 8192 / max(page.rect.width, page.rect.height))
                png = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True).tobytes("png")
        except Exception as error:
            raise ValueError(f"cannot rasterize SVG resource {resource.id!r}: {error}") from error
        self.report.add(
            IssueSeverity.LOSS,
            "image-vector",
            f"SVG resource {resource.id!r} rasterized for the PDF HTML backend; vector editability is lost",
        )
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
