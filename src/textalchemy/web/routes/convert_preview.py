"""HTTP-адаптеры постраничного предпросмотра сохранённой конвертации."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import Response

from textalchemy.web.app import app
from textalchemy.web.preview import DEFAULT_PREVIEW_DPI
from textalchemy.web.routes import convert as facade
from textalchemy.web.services.conversion_preview import ConversionPreviewService, PreviewError, PreviewImage


def _service() -> ConversionPreviewService:
    return ConversionPreviewService(store=facade.tasks_store, counter=facade.cached_page_count, renderer=facade.cached_page_png)


def _image_response(image: PreviewImage) -> Response:
    headers = {"Cache-Control": "private, no-cache, max-age=0"}
    if image.similarity is not None:
        headers["X-Visual-Similarity"] = f"{image.similarity:.4f}"
        headers["X-Visual-RMSE"] = f"{image.rmse:.4f}"
    return Response(image.content, media_type="image/png", headers=headers)


@app.get("/api/convert/preview/{task_id}/meta")
def api_convert_preview_meta(task_id: str) -> dict[str, Any]:
    try:
        return _service().meta(task_id)
    except PreviewError as error:
        raise HTTPException(error.status_code, str(error)) from error


@app.get("/api/convert/preview/{task_id}")
def api_convert_preview(task_id: str, side: str = "source", page: int = 1, dpi: int = DEFAULT_PREVIEW_DPI) -> Response:
    try:
        return _image_response(_service().page(task_id, side=side, page=page, dpi=dpi))
    except PreviewError as error:
        raise HTTPException(error.status_code, str(error)) from error


@app.get("/api/convert/preview/{task_id}/diff")
def api_convert_preview_diff(task_id: str, page: int = 1, dpi: int = DEFAULT_PREVIEW_DPI) -> Response:
    try:
        return _image_response(_service().diff(task_id, page=page, dpi=dpi))
    except PreviewError as error:
        raise HTTPException(error.status_code, str(error)) from error
