"""PPTX → автономный HTML-вьювер через pipeline.

Эта операция — pipeline-обёртка над ``textalchemy.convert.pptx_to_html``.
Используется в CLI и в YAML-конвейерах.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

from textalchemy.core.registry import operation
from textalchemy.core.types import Document

logger = logging.getLogger(__name__)


@operation(
    "render.html.pptx",
    input_type="Document",
    output_type="ConversionResult",
    input_param="doc",
    description="Document (.pptx) → автономный HTML-просмотрщик в output_dir.",
    tags=["render", "pptx"],
)
def render_html_pptx(
    *,
    doc: Document,
    output_dir: Union[str, Path],
    copy_assets: bool = True,
):
    """PPTX → HTML. ``output_dir`` — директория для результата.

    Возвращает ``ConversionResult`` от ``PptxToHtmlConverter`` (а не
    голый Path), чтобы соответствовать контракту конвертеров.
    """
    from textalchemy.convert.base import ConversionResult
    from textalchemy.convert.pptx_to_html import PptxToHtmlConverter

    if doc.format.value != "pptx":
        logger.warning("render.html.pptx: not a pptx: format=%s", doc.format.value)
        return ConversionResult(
            input_path=Path(doc.path), output_path=Path(output_dir),
            success=False, error=f"not a pptx: format={doc.format.value}",
        )

    converter = PptxToHtmlConverter(copy_assets=copy_assets)
    return converter.convert(doc.path, output_dir)


__all__ = ["render_html_pptx"]
