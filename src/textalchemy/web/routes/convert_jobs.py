"""HTTP endpoints пакетной конвертации и истории заданий."""

from __future__ import annotations

import uuid

from fastapi import File, Form, HTTPException, UploadFile

from textalchemy.convert.executor import ConversionExecutor
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.object_quality_policy import ObjectLossPolicy
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.text_quality_policy import resolve_text_policy
from textalchemy.core.types import DocFormat
from textalchemy.web.app import app
from textalchemy.web.routes import convert as facade

_BATCH_LIMIT = 20
_JOBS_HISTORY_LIMIT = 20


def _check_route(
    executor: ConversionExecutor,
    source: DocFormat,
    target: DocFormat,
    mode: ConversionMode,
    min_retention: float,
) -> None:
    if target not in facade._OUTPUT_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Формат результата {target.value} пока недоступен в Web UI")
    plan = executor.plan(source, target, mode=mode)
    if plan is None or not facade._web_plan_supported(plan):
        raise HTTPException(status_code=400, detail=f"Маршрут {source.value} → {target.value} ({mode.value}) недоступен")
    below = facade._preservation_below(plan, min_retention)
    if below:
        details = ", ".join(f"{name}: {score:.0%}" for name, score in below.items())
        raise HTTPException(status_code=422, detail=f"Прогноз ниже выбранного порога {min_retention:.0%}: {details}")


@app.post("/api/convert/batch")
async def api_convert_batch(
    files: list[UploadFile] = File(...),
    target_format: str = Form(""),
    mode: str = Form("balanced"),
    min_retention: float = Form(0.0),
    max_loss_issues: int | None = Form(None, ge=0),
    max_lost_objects: int | None = Form(None, ge=0),
    require_unchanged_text: bool = Form(False),
    text_preservation: str | None = Form(None),
    max_text_edits: int | None = Form(None, ge=0),
):
    try:
        conversion_mode = ConversionMode(mode)
        resolve_text_policy(require_unchanged_text, text_preservation, max_text_edits)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not files:
        raise HTTPException(status_code=400, detail="Не передано ни одного файла")
    if len(files) > _BATCH_LIMIT:
        raise HTTPException(status_code=400, detail=f"Слишком много файлов: максимум {_BATCH_LIMIT}")
    executor = ConversionExecutor()
    policy = QualityPolicy(max_loss_issues) if max_loss_issues is not None else None
    object_policy = ObjectLossPolicy(max_lost_objects) if max_lost_objects is not None else None
    workspaces = []
    prepared = []
    try:
        for upload in files:
            workspace = facade.create_web_workspace()
            workspaces.append(workspace)
            source_path = await facade.save_upload(workspace, upload, fallback="document")
            source, target = facade._resolve_conversion(
                source_path,
                source_format="auto",
                target_format=target_format,
                legacy_format="",
            )
            _check_route(executor, source, target, conversion_mode, min_retention)
            prepared.append((workspace, source_path, source, target))
    except Exception:
        for workspace in workspaces:
            workspace.cleanup()
        raise

    tasks: list[dict[str, object]] = []
    submissions: list[str] = []
    try:
        for workspace, source_path, source, target in prepared:
            task_id = str(uuid.uuid4())
            facade._persist_conversion_task(
                task_id, source_path, source, target, conversion_mode, policy, object_policy,
                require_unchanged_text, text_preservation, max_text_edits,
            )
            workspace.cleanup()
            submissions.append(task_id)
            tasks.append({
                "name": source_path.name,
                "task_id": task_id,
                "source_format": source.value,
                "target_format": target.value,
                "status": f"/api/convert/status/{task_id}",
                "result": f"/api/convert/result/{task_id}",
            })
        job_id = str(uuid.uuid4())
        facade.tasks_store.set_job(job_id, {
            "job_id": job_id,
            "target_format": target_format,
            "mode": conversion_mode.value,
            "max_loss_issues": max_loss_issues,
            "max_lost_objects": max_lost_objects,
            "require_unchanged_text": require_unchanged_text,
            "text_preservation": text_preservation,
            "max_text_edits": max_text_edits,
            "files": tasks,
        })
    except Exception:
        for workspace in workspaces:
            workspace.cleanup()
        for task in tasks:
            facade.tasks_store.delete(str(task["task_id"]))
        raise
    for task_id in submissions:
        try:
            facade.resume_conversion_task(task_id)
        except RuntimeError as error:
            task = facade.tasks_store.get(task_id) or {}
            facade._register_task(task_id, {**task, "status": "queued", "error": f"Ожидает перезапуска очереди: {error}"})
    return {"success": True, "job_id": job_id, "tasks": tasks}


@app.get("/api/convert/jobs")
async def api_convert_jobs():
    result = []
    for job in facade.tasks_store.list_jobs(limit=_JOBS_HISTORY_LIMIT):
        files = job.get("files", [])
        counts = {"queued": 0, "running": 0, "done": 0, "error": 0, "expired": 0, "interrupted": 0}
        for item in files:
            task = facade.tasks_store.get(item["task_id"])
            status = task["status"] if task else "expired"
            counts[status] = counts.get(status, 0) + 1
        result.append({
            "job_id": job["job_id"], "created": job.get("_ts"), "target_format": job.get("target_format"),
            "mode": job.get("mode"), "files": [item["name"] for item in files], "counts": counts,
        })
    return {"jobs": result}


@app.get("/api/convert/jobs/{job_id}")
async def api_convert_job(job_id: str):
    job = facade.tasks_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    entries = []
    for item in job.get("files", []):
        task = facade.tasks_store.get(item["task_id"])
        entry: dict[str, object] = {
            "name": item["name"], "task_id": item["task_id"],
            "status_url": item.get("status"), "result_url": item.get("result"),
        }
        if task is None:
            entry.update(status="expired", error="Истёк срок хранения результата")
        else:
            entry.update(facade._public_task_payload(task))
        entries.append(entry)
    return {"job_id": job_id, "target_format": job.get("target_format"), "mode": job.get("mode"), "tasks": entries}


@app.delete("/api/convert/jobs/{job_id}")
async def api_convert_job_delete(job_id: str):
    job = facade.tasks_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    for item in job.get("files", []):
        facade.tasks_store.delete(item["task_id"])
    facade.tasks_store.delete_job(job_id)
    return {"success": True, "job_id": job_id}


@app.post("/api/convert/jobs/{job_id}/rerun")
async def api_convert_job_rerun(job_id: str):
    job = facade.tasks_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        conversion_mode = ConversionMode(job["mode"])
    except (KeyError, ValueError):
        conversion_mode = ConversionMode.BALANCED
    executor = ConversionExecutor()
    submissions = []
    for item in job.get("files", []):
        task_id = item["task_id"]
        source_path = facade.tasks_store.source_path(task_id)
        if source_path is None:
            continue
        task = facade.tasks_store.get(task_id) or {}
        if task.get("status") in {"queued", "running", "cancelling"}:
            continue
        source, target = DocFormat(item["source_format"]), DocFormat(item["target_format"])
        plan = executor.plan(source, target, mode=conversion_mode)
        if plan is None or not facade._web_plan_supported(plan):
            continue
        facade.tasks_store.clear_result(task_id)
        facade._register_task(task_id, {
            **task,
            "status": "queued", "queue_kind": "convert", "error": None, "report": None,
            "artifact": None, "max_loss_issues": task.get("max_loss_issues", job.get("max_loss_issues")),
            "max_lost_objects": task.get("max_lost_objects", job.get("max_lost_objects")),
            "require_unchanged_text": task.get("require_unchanged_text", job.get("require_unchanged_text", False)),
            "text_preservation": task.get("text_preservation", job.get("text_preservation")),
            "max_text_edits": task.get("max_text_edits", job.get("max_text_edits")),
            "source_format": source.value, "target_format": target.value, "mode": conversion_mode.value,
        })
        submissions.append(task_id)
    launched = []
    for task_id in submissions:
        try:
            facade.resume_conversion_task(task_id)
            launched.append(task_id)
        except RuntimeError as error:
            task = facade.tasks_store.get(task_id) or {}
            facade._register_task(task_id, {**task, "status": "queued", "error": f"Ожидает перезапуска очереди: {error}"})
    return {"success": True, "job_id": job_id, "launched": launched}
