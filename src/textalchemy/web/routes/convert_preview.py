"""HTTP endpoints рендеринга постраничного preview конвертации."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import Response

from textalchemy.quality.visual import difference_heatmap_png
from textalchemy.web.app import app
from textalchemy.web.preview import DEFAULT_PREVIEW_DPI, MAX_PREVIEW_DPI
from textalchemy.web.routes import convert as facade

_PREVIEW_SIDES = ("source", "target")


def _side_meta(preview_dir: Path, file: Path | None, side: str) -> dict[str, object]:
    if file is None or not file.is_file():
        return {"available": False, "pages": 0, "error": None}
    try:
        pages = facade.cached_page_count(preview_dir, file, side)
    except Exception as error:  # noqa: BLE001 - preview must never break the API
        return {"available": False, "pages": 0, "error": str(error)}
    return {"available": pages > 0, "pages": pages, "error": None}


@app.get("/api/convert/preview/{task_id}/meta")
async def api_convert_preview_meta(task_id: str):
    task = facade.tasks_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "done":
        raise HTTPException(status_code=409, detail="Preview is not ready")
    preview_dir = facade.tasks_store.preview_dir(task_id)
    return {
        "source": _side_meta(preview_dir, facade.tasks_store.source_path(task_id), "source"),
        "target": _side_meta(
            preview_dir,
            facade.tasks_store.result_path(task_id, task.get("artifact", "")),
            "target",
        ),
    }


@app.get("/api/convert/preview/{task_id}")
async def api_convert_preview(task_id: str, side: str = "source", page: int = 1, dpi: int = DEFAULT_PREVIEW_DPI):
    if side not in _PREVIEW_SIDES:
        raise HTTPException(status_code=400, detail="side must be 'source' or 'target'")
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be positive")
    task = facade.tasks_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "done":
        raise HTTPException(status_code=409, detail="Preview is not ready")
    preview_dir = facade.tasks_store.preview_dir(task_id)
    file = (
        facade.tasks_store.source_path(task_id)
        if side == "source"
        else facade.tasks_store.result_path(task_id, task.get("artifact", ""))
    )
    if file is None or not file.is_file():
        raise HTTPException(status_code=404, detail="Source file is not available")
    try:
        pages = facade.cached_page_count(preview_dir, file, side)
    except Exception:  # noqa: BLE001 - preview must never break the API
        pages = 0
    if page > pages:
        raise HTTPException(status_code=404, detail="Page is out of range")
    data = facade.cached_page_png(preview_dir, file, side, page - 1, dpi=min(dpi, MAX_PREVIEW_DPI))
    if data is None:
        raise HTTPException(status_code=404, detail="Не удалось отрисовать страницу")
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/convert/preview/{task_id}/diff")
async def api_convert_preview_diff(task_id: str, page: int = 1, dpi: int = DEFAULT_PREVIEW_DPI):
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be positive")
    task = facade.tasks_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "done":
        raise HTTPException(status_code=409, detail="Preview is not ready")
    preview_dir = facade.tasks_store.preview_dir(task_id)
    source = facade.tasks_store.source_path(task_id)
    target = facade.tasks_store.result_path(task_id, task.get("artifact", ""))
    if source is None or target is None:
        raise HTTPException(status_code=404, detail="Source or result is not available")
    render_dpi = min(dpi, MAX_PREVIEW_DPI)
    source_png = facade.cached_page_png(preview_dir, source, "source", page - 1, dpi=render_dpi)
    target_png = facade.cached_page_png(preview_dir, target, "target", page - 1, dpi=render_dpi)
    if source_png is None or target_png is None:
        raise HTTPException(status_code=404, detail="Не удалось отрисовать сравниваемые страницы")
    data, comparison = difference_heatmap_png(source_png, target_png)
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Visual-Similarity": f"{comparison.similarity:.4f}",
            "X-Visual-RMSE": f"{comparison.root_mean_square_error:.4f}",
        },
    )
