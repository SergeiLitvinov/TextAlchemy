"""Основные HTTP endpoints конвертации и совместимый facade для дочерних route-модулей."""

from __future__ import annotations

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
from textalchemy.web.services.conversion_catalog import available_conversions as _available_conversions
from textalchemy.web.services.conversion_catalog import resolve_conversion as _resolve_conversion
from textalchemy.web.services.conversion_inspection import ConversionInspectionService
from textalchemy.web.services.conversion_submission import (
    ConversionRequestError,
    ConversionSettings,
    ConversionSubmissionService,
    SubmissionUnavailableError,
)
from textalchemy.web.services.conversion_tasks import ConversionTaskService
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
    max_changed_formulas: int | None = None,
    max_changed_emphasis: int | None = None,
) -> None:
    """Compatibility wrapper around the application service."""
    _task_service().persist(
        task_id,
        source_path,
        source,
        target,
        mode,
        quality_policy,
        object_loss_policy,
        require_unchanged_text,
        text_preservation,
        max_text_edits,
        max_changed_formulas,
        max_changed_emphasis,
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
    service = ConversionInspectionService(workspace_factory=create_web_workspace, saver=save_upload, inspector=inspect_path)
    try:
        return await service.inspect(file)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(400, f"Не удалось проверить структуру документа: {error}") from error


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
    max_changed_formulas: int | None = Form(None, ge=0),
    max_changed_emphasis: int | None = Form(None, ge=0),
):
    service = ConversionSubmissionService(
        store=tasks_store,
        persist=_persist_conversion_task,
        resume=resume_conversion_task,
        workspace_factory=create_web_workspace,
        saver=save_upload,
        resolver=_resolve_conversion,
        executor_factory=ConversionExecutor,
    )
    settings = ConversionSettings(
        target_format,
        mode,
        max_loss_issues,
        max_lost_objects,
        require_unchanged_text,
        text_preservation,
        max_text_edits,
        max_changed_formulas,
        max_changed_emphasis,
    )
    try:
        return await service.submit(
            file,
            settings=settings,
            source_format=source_format,
            legacy_format=fmt,
            min_retention=min_retention,
        )
    except HTTPException:
        raise
    except ConversionRequestError as error:
        raise HTTPException(error.status_code, str(error)) from error
    except SubmissionUnavailableError as error:
        raise HTTPException(503, str(error)) from error
    except Exception as error:
        raise HTTPException(503, "Очередь конвертации временно недоступна") from error


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
