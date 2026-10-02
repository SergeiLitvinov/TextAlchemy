"""HTTP-адаптеры пакетной конвертации и истории заданий."""

from __future__ import annotations

from typing import Any

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from textalchemy.web.app import app
from textalchemy.web.routes import convert as facade
from textalchemy.web.services.batch_actions import cancel_batch
from textalchemy.web.services.batch_archive import build_batch_archive
from textalchemy.web.services.batch_history import BatchHistoryService
from textalchemy.web.services.batch_retry import BatchRetryService
from textalchemy.web.services.batch_submission import BatchRequestError, BatchSettings, BatchSubmissionService


def _submission_service() -> BatchSubmissionService:
    return BatchSubmissionService(
        store=facade.tasks_store,
        persist=facade._persist_conversion_task,
        resume=facade.resume_conversion_task,
        workspace_factory=facade.create_web_workspace,
        saver=facade.save_upload,
        resolver=facade._resolve_conversion,
        executor_factory=facade.ConversionExecutor,
    )


def _history_service() -> BatchHistoryService:
    return BatchHistoryService(facade.tasks_store, facade._public_task_payload)


@app.post("/api/convert/batch")
async def api_convert_batch(
    files: list[UploadFile] = File(...),
    target_format: str = Form(""),
    mode: str = Form("balanced"),
    file_options: str = Form(""),
    min_retention: float = Form(0.0),
    max_loss_issues: int | None = Form(None, ge=0),
    max_lost_objects: int | None = Form(None, ge=0),
    require_unchanged_text: bool = Form(False),
    text_preservation: str | None = Form(None),
    max_text_edits: int | None = Form(None, ge=0),
    max_changed_formulas: int | None = Form(None, ge=0),
    max_changed_emphasis: int | None = Form(None, ge=0),
) -> dict[str, Any]:
    settings = BatchSettings(
        target_format=target_format,
        mode=mode,
        max_loss_issues=max_loss_issues,
        max_lost_objects=max_lost_objects,
        require_unchanged_text=require_unchanged_text,
        text_preservation=text_preservation,
        max_text_edits=max_text_edits,
        max_changed_formulas=max_changed_formulas,
        max_changed_emphasis=max_changed_emphasis,
    )
    try:
        return await _submission_service().submit(
            files, settings=settings, file_options=file_options, min_retention=min_retention
        )
    except BatchRequestError as error:
        raise HTTPException(error.status_code, str(error)) from error


@app.get("/api/convert/jobs")
async def api_convert_jobs() -> dict[str, Any]:
    return _history_service().list()


@app.get("/api/convert/jobs/{job_id}")
async def api_convert_job(job_id: str) -> dict[str, Any]:
    try:
        return _history_service().get(job_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@app.delete("/api/convert/jobs/{job_id}")
async def api_convert_job_delete(job_id: str) -> dict[str, Any]:
    try:
        return _history_service().delete(job_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@app.get("/api/convert/jobs/{job_id}/archive")
def api_convert_job_archive(job_id: str, task_ids: str | None = None):
    try:
        stream = build_batch_archive(facade.tasks_store, job_id, task_ids=task_ids)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except OverflowError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=409, detail="Результаты изменились или недоступны. Обновите пакет и повторите скачивание."
        ) from error

    def chunks():
        try:
            while chunk := stream.read(1024 * 1024):
                yield chunk
        finally:
            stream.close()

    return StreamingResponse(
        chunks(),
        media_type="application/zip",
        background=BackgroundTask(stream.close),
        headers={"Content-Disposition": 'attachment; filename="converted-batch.zip"'},
    )


@app.post("/api/convert/jobs/{job_id}/rerun")
async def api_convert_job_rerun(
    job_id: str,
    request: Request,
    failed_only: bool = Form(False),
    task_ids: str | None = Form(None),
) -> dict[str, Any]:
    if task_ids is None and "task_ids" in await request.form():
        raise HTTPException(400, "Выберите хотя бы один файл пакета")
    service = BatchRetryService(facade.tasks_store, facade.resume_conversion_task, facade.ConversionExecutor)
    try:
        return service.rerun(job_id, failed_only=failed_only, task_ids=task_ids)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.post("/api/convert/jobs/{job_id}/cancel")
async def api_convert_job_cancel(job_id: str, request: Request, task_ids: str | None = Form(None)):
    if task_ids is None and "task_ids" in await request.form():
        raise HTTPException(400, "Выберите хотя бы один файл пакета")
    try:
        return cancel_batch(facade.tasks_store, job_id, cancel_task=facade._task_service().cancel, task_ids=task_ids)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
