"""Основные HTTP endpoints конвертации и совместимый facade для дочерних route-модулей."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from textalchemy.convert.executor import ConversionExecutor
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.inspection import compare_inspections, inspect_path
from textalchemy.core.object_quality_policy import ObjectLossPolicy
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.types import DocFormat
from textalchemy.web.app import (
    _register_task,  # noqa: F401 - compatibility facade for job routes and tests
    app,
    task_queue,
    tasks_store,
)
from textalchemy.web.preview import cached_page_count, cached_page_png  # noqa: F401 - compatibility facade
from textalchemy.web.services.conversion_catalog import OUTPUT_SUFFIXES as _OUTPUT_SUFFIXES
from textalchemy.web.services.conversion_catalog import available_conversions as _available_conversions
from textalchemy.web.services.conversion_catalog import preservation_below as _preservation_below
from textalchemy.web.services.conversion_catalog import resolve_conversion as _resolve_conversion
from textalchemy.web.services.conversion_catalog import web_plan_supported as _web_plan_supported
from textalchemy.web.services.conversion_tasks import ConversionTaskService
from textalchemy.web.services.conversion_tasks import inspection_payload as _inspection_payload
from textalchemy.web.workspace import create_web_workspace, save_upload


def _public_task_payload(task: dict[str, object]) -> dict[str, object]:
    """Публичная проекция метаданных задачи без артефактов и служебных полей."""
    hidden = {"artifact", "content", "_ts", "media_type", "filename"}
    return {key: value for key, value in task.items() if key not in hidden} | (
        {"filename": task["filename"]} if task.get("filename") else {}
    )


def _task_service() -> ConversionTaskService:
    return ConversionTaskService(
        store=tasks_store,
        queue=task_queue,
        workspace_factory=create_web_workspace,
        inspector=inspect_path,
        comparer=compare_inspections,
    )


def _persist_conversion_task(
    task_id: str,
    source_path: Path,
    source: DocFormat,
    target: DocFormat,
    mode: ConversionMode,
    quality_policy: QualityPolicy | None = None,
    object_loss_policy: ObjectLossPolicy | None = None,
    require_unchanged_text: bool = False,
    text_preservation: str | None = None,
    max_text_edits: int | None = None,
) -> None:
    """Compatibility wrapper around the application service."""
    _task_service().persist(
        task_id, source_path, source, target, mode, quality_policy, object_loss_policy,
        require_unchanged_text, text_preservation, max_text_edits,
    )


def _run_stored_conversion(task_id: str) -> None:
    """Compatibility wrapper used by recovery and existing integrations."""
    _task_service().run_stored(task_id)


def resume_conversion_task(task_id: str) -> None:
    """Submit through the route facade while preserving injected test dependencies."""
    task_queue.submit_named(task_id, _run_stored_conversion, task_id)


@app.get("/api/convert/capabilities")
async def api_convert_capabilities():
    return _available_conversions(ConversionExecutor())


@app.post("/api/convert/inspect")
async def api_convert_inspect(file: UploadFile = File(...)):
    workspace = create_web_workspace()
    try:
        source_path = await save_upload(workspace, file, fallback="document")
        inspection = inspect_path(source_path)
        return {"success": True, "inspection": _inspection_payload(inspection, source_path.name)}
    except HTTPException:
        raise
    except Exception as error:  # noqa: BLE001 - API boundary returns stable validation errors
        raise HTTPException(status_code=400, detail=f"Не удалось проверить структуру документа: {error}") from error
    finally:
        workspace.cleanup()


@app.post("/api/convert")
async def api_convert(
    file: UploadFile = File(...),
    source_format: str = Form("auto"),
    target_format: str = Form(""),
    mode: str = Form("balanced"),
    fmt: str = Form(""),
    min_retention: float = Form(0.0),
    max_loss_issues: int | None = Form(None, ge=0),
    max_lost_objects: int | None = Form(None, ge=0),
    require_unchanged_text: bool = Form(False),
    text_preservation: str | None = Form(None),
    max_text_edits: int | None = Form(None, ge=0),
):
    workspace = create_web_workspace()
    try:
        source_path = await save_upload(workspace, file, fallback="document")
        source, target = _resolve_conversion(
            source_path,
            source_format=source_format,
            target_format=target_format,
            legacy_format=fmt,
        )
        conversion_mode = ConversionMode(mode)
        plan = ConversionExecutor().plan(source, target, mode=conversion_mode)
        if plan is None or not _web_plan_supported(plan):
            raise HTTPException(
                status_code=400,
                detail=f"Маршрут {source.value} → {target.value} ({conversion_mode.value}) недоступен",
            )
        if target not in _OUTPUT_SUFFIXES:
            raise HTTPException(status_code=400, detail=f"Формат результата {target.value} пока недоступен в Web UI")
        below = _preservation_below(plan, min_retention)
        if below:
            details = ", ".join(f"{name}: {score:.0%}" for name, score in below.items())
            raise HTTPException(
                status_code=422,
                detail=f"Прогноз ниже выбранного порога {min_retention:.0%}: {details}",
            )
        task_id = str(uuid.uuid4())
        policy = QualityPolicy(max_loss_issues) if max_loss_issues is not None else None
        object_policy = ObjectLossPolicy(max_lost_objects) if max_lost_objects is not None else None
        _persist_conversion_task(
            task_id, source_path, source, target, conversion_mode, policy, object_policy,
            require_unchanged_text, text_preservation, max_text_edits,
        )
    except HTTPException:
        workspace.cleanup()
        raise
    except ValueError as error:
        workspace.cleanup()
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        workspace.cleanup()
        raise HTTPException(status_code=503, detail="Очередь конвертации временно недоступна") from error
    workspace.cleanup()
    try:
        resume_conversion_task(task_id)
    except Exception as error:
        raise HTTPException(status_code=503, detail="Очередь конвертации временно недоступна") from error
    return {
        "success": True,
        "task_id": task_id,
        "status": f"/api/convert/status/{task_id}",
        "result": f"/api/convert/result/{task_id}",
    }


@app.get("/api/convert/status/{task_id}")
async def api_convert_status(task_id: str):
    task = tasks_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _public_task_payload(task)


@app.get("/api/convert/result/{task_id}")
async def api_convert_result(task_id: str):
    task = tasks_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "done":
        raise HTTPException(status_code=409, detail="Result is not ready")
    artifact_path = tasks_store.result_path(task_id, task.get("artifact", ""))
    if artifact_path is None:
        raise HTTPException(status_code=500, detail="Не удалось подготовить файл")
    return FileResponse(artifact_path, media_type=task["media_type"], filename=task["filename"])


# Imported last: these modules use this file as a monkeypatch-friendly compatibility facade.
from textalchemy.web.routes import convert_jobs as _convert_jobs  # noqa: E402,F401
from textalchemy.web.routes import convert_preview as _convert_preview  # noqa: E402,F401
