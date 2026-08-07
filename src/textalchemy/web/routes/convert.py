"""Web API конвертации через единый capability planner."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest, infer_format
from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.core.conversion_graph import ConversionPlan
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.inspection import compare_inspections, inspect_path
from textalchemy.core.types import DocFormat
from textalchemy.web.app import _register_task, app, tasks_store
from textalchemy.web.preview import (
    DEFAULT_PREVIEW_DPI,
    MAX_PREVIEW_DPI,
    cached_page_count,
    cached_page_png,
)
from textalchemy.web.workspace import create_web_workspace, save_upload

_LEGACY_CONVERSIONS = {
    "pdf": (DocFormat.PDF, DocFormat.DOCX),
    "pptx": (DocFormat.PPTX, DocFormat.HTML),
    "latex": (DocFormat.DOCX, DocFormat.LATEX),
}
_DEFAULT_TARGETS = {
    DocFormat.PDF: DocFormat.DOCX,
    DocFormat.PPTX: DocFormat.HTML,
    DocFormat.DOCX: DocFormat.PDF,
    DocFormat.MODEL: DocFormat.DOCX,
}
_OUTPUT_SUFFIXES = {
    DocFormat.DOCX: ".docx",
    DocFormat.HTML: ".html",
    DocFormat.LATEX: ".tex",
    DocFormat.PDF: ".pdf",
    DocFormat.MODEL: ".json",
}
_MEDIA_TYPES = {
    DocFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    DocFormat.HTML: "text/html; charset=utf-8",
    DocFormat.LATEX: "application/x-tex",
    DocFormat.PDF: "application/pdf",
    DocFormat.MODEL: "application/json",
}
_FORMAT_LABELS = {
    DocFormat.PDF: "PDF",
    DocFormat.DOCX: "Word (DOCX)",
    DocFormat.PPTX: "PowerPoint (PPTX)",
    DocFormat.HTML: "HTML",
    DocFormat.LATEX: "LaTeX",
    DocFormat.MODEL: "TextAlchemy Model",
}
_SOURCE_EXTENSIONS = {
    DocFormat.PDF: (".pdf",),
    DocFormat.DOCX: (".docx",),
    DocFormat.PPTX: (".pptx",),
    DocFormat.MODEL: (".json",),
}
_MODE_ORDER = (ConversionMode.BALANCED, ConversionMode.FAITHFUL, ConversionMode.EDITABLE)
_BATCH_LIMIT = 20
_JOBS_HISTORY_LIMIT = 20


def _public_task_payload(task: dict[str, object]) -> dict[str, object]:
    """Публичная проекция метаданных задачи (без артефактов и служебных полей)."""
    return {
        key: value
        for key, value in task.items()
        if key not in {"artifact", "content", "_ts", "media_type", "filename"}
    } | ({"filename": task["filename"]} if task.get("filename") else {})


def _resolve_conversion(
    source_path: Path,
    *,
    source_format: str,
    target_format: str,
    legacy_format: str,
) -> tuple[DocFormat, DocFormat]:
    if source_format == "auto" and legacy_format in _LEGACY_CONVERSIONS:
        legacy_source, legacy_target = _LEGACY_CONVERSIONS[legacy_format]
        return legacy_source, DocFormat(target_format) if target_format else legacy_target
    source = infer_format(source_path) if source_format == "auto" else DocFormat(source_format)
    target = DocFormat(target_format) if target_format else _DEFAULT_TARGETS.get(source)
    if target is None:
        raise ValueError(f"Для формата {source.value} не задан формат результата")
    return source, target


def _artifact_meta(output_path: Path, source_stem: str, target: DocFormat) -> tuple[str, str]:
    """Определить (filename, media_type) артефакта; каталоги отдаём zip-архивом."""
    if output_path.is_dir():
        return f"{source_stem}-html", "application/zip"
    return output_path.name, _MEDIA_TYPES[target]


def _web_plan_supported(plan: ConversionPlan) -> bool:
    """Web executor safely supports direct routes and intermediate DocumentModel values."""

    return all(step.target is DocFormat.MODEL for step in plan.steps[:-1])


def _inspection_payload(inspection, display_name: str) -> dict[str, object] | None:
    if inspection is None:
        return None
    payload = inspection.to_dict()
    payload["source_path"] = display_name
    return payload


def _available_conversions(executor: ConversionExecutor) -> dict[str, object]:
    sources = []
    for source, extensions in _SOURCE_EXTENSIONS.items():
        targets = []
        for target in _OUTPUT_SUFFIXES:
            if target is source:
                continue
            plans = {
                mode.value: plan
                for mode in _MODE_ORDER
                if (plan := executor.plan(source, target, mode=mode)) is not None and _web_plan_supported(plan)
            }
            if not plans:
                continue
            targets.append(
                {
                    "format": target.value,
                    "label": _FORMAT_LABELS[target],
                    "extension": _OUTPUT_SUFFIXES[target],
                    "modes": list(plans),
                    "plans": {
                        mode: {
                            "lossless": plan.lossless,
                            "steps": [step.id for step in plan.steps],
                            "descriptions": [step.description or step.id for step in plan.steps],
                        }
                        for mode, plan in plans.items()
                    },
                }
            )
        if targets:
            sources.append(
                {
                    "format": source.value,
                    "label": _FORMAT_LABELS[source],
                    "extensions": list(extensions),
                    "targets": targets,
                }
            )
    return {
        "sources": sources,
        "modes": [mode.value for mode in _MODE_ORDER],
    }


def _run_convert(
    task_id: str,
    source_path: Path,
    output_path: Path,
    source: DocFormat,
    target: DocFormat,
    mode: ConversionMode,
    workspace: ArtifactWorkspace,
    keep_source: bool = False,
) -> None:
    source_inspection = None
    inspection_error = None
    try:
        if keep_source:
            tasks_store.store_source(task_id, source_path, source_path.name)
        try:
            source_inspection = inspect_path(source_path)
        except Exception as error:  # noqa: BLE001 - inspection must not block conversion
            inspection_error = f"Не удалось проверить исходный документ: {error}"
        report = ConversionExecutor().execute(
            ConversionRequest(
                input_path=source_path,
                output_path=output_path,
                source=source,
                target=target,
                mode=mode,
            )
        )
        report_payload = report.to_dict()
        if not report.success:
            error = next(
                (issue["message"] for issue in report_payload["issues"] if issue["severity"] == "error"),
                "Конвертация завершилась с ошибкой",
            )
            _register_task(
                task_id,
                {
                    "status": "error",
                    "error": error,
                    "report": report_payload,
                    "source_inspection": _inspection_payload(source_inspection, source_path.name),
                    "inspection_error": inspection_error,
                },
            )
            return
        workspace.validate_artifact(output_path)
        filename, media_type = _artifact_meta(output_path, source_path.stem, target)
        artifact_name = tasks_store.store_artifact(task_id, output_path, filename)
        target_inspection = None
        comparison = None
        if source_inspection is not None and output_path.is_file():
            try:
                target_inspection = inspect_path(output_path)
                comparison = compare_inspections(source_inspection, target_inspection)
            except Exception as error:  # noqa: BLE001 - unsupported targets still remain downloadable
                inspection_error = f"Структурное сравнение результата недоступно: {error}"
        _register_task(
            task_id,
            {
                "status": "done",
                "artifact": artifact_name,
                "filename": filename,
                "media_type": media_type,
                "error": None,
                "report": report_payload,
                "source_inspection": _inspection_payload(source_inspection, source_path.name),
                "target_inspection": _inspection_payload(target_inspection, filename),
                "comparison": comparison.to_dict() if comparison is not None else None,
                "inspection_error": inspection_error,
            },
        )
    except Exception as error:  # noqa: BLE001 - background task must expose a stable status
        _register_task(
            task_id,
            {
                "status": "error",
                "error": str(error),
                "report": None,
                "source_inspection": _inspection_payload(source_inspection, source_path.name),
                "inspection_error": inspection_error,
            },
        )
    finally:
        workspace.cleanup()


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
    except Exception as error:  # noqa: BLE001 - API boundary returns a stable validation error
        raise HTTPException(status_code=400, detail=f"Не удалось проверить структуру документа: {error}") from error
    finally:
        workspace.cleanup()


@app.post("/api/convert")
async def api_convert(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source_format: str = Form("auto"),
    target_format: str = Form(""),
    mode: str = Form("balanced"),
    fmt: str = Form(""),
    tool: str = Form(""),  # retained for compatibility with older clients
):
    del tool
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
    except HTTPException:
        workspace.cleanup()
        raise
    except ValueError as error:
        workspace.cleanup()
        raise HTTPException(status_code=400, detail=str(error)) from error

    plan = ConversionExecutor().plan(source, target, mode=conversion_mode)
    if plan is None or not _web_plan_supported(plan):
        workspace.cleanup()
        raise HTTPException(
            status_code=400,
            detail=f"Маршрут {source.value} → {target.value} ({conversion_mode.value}) недоступен",
        )

    if target not in _OUTPUT_SUFFIXES:
        workspace.cleanup()
        raise HTTPException(status_code=400, detail=f"Формат результата {target.value} пока недоступен в Web UI")
    output_path = (
        workspace.artifact_path(f"{source_path.stem}-html")
        if source is DocFormat.PPTX and target is DocFormat.HTML
        else workspace.artifact_path(f"{source_path.stem}{_OUTPUT_SUFFIXES[target]}")
    )
    task_id = str(uuid.uuid4())
    _register_task(
        task_id,
        {
            "status": "running",
            "error": None,
            "report": None,
            "source_format": source.value,
            "target_format": target.value,
            "mode": conversion_mode.value,
        },
    )
    background_tasks.add_task(_run_convert, task_id, source_path, output_path, source, target, conversion_mode, workspace, True)
    return {
        "success": True,
        "task_id": task_id,
        "status": f"/api/convert/status/{task_id}",
        "result": f"/api/convert/result/{task_id}",
    }


_PREVIEW_SIDES = ("source", "target")


def _preview_side_meta(preview_dir: Path, file: Path | None, side: str) -> dict[str, object]:
    if file is None or not file.is_file():
        return {"available": False, "pages": 0, "error": None}
    try:
        pages = cached_page_count(preview_dir, file, side)
    except Exception as error:  # noqa: BLE001 - preview must never break the API
        return {"available": False, "pages": 0, "error": str(error)}
    return {"available": pages > 0, "pages": pages, "error": None}


@app.get("/api/convert/preview/{task_id}/meta")
async def api_convert_preview_meta(task_id: str):
    task = tasks_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "done":
        raise HTTPException(status_code=409, detail="Preview is not ready")
    preview_dir = tasks_store.preview_dir(task_id)
    return {
        "source": _preview_side_meta(preview_dir, tasks_store.source_path(task_id), "source"),
        "target": _preview_side_meta(
            preview_dir,
            tasks_store.result_path(task_id, task.get("artifact", "")),
            "target",
        ),
    }


@app.get("/api/convert/preview/{task_id}")
async def api_convert_preview(task_id: str, side: str = "source", page: int = 1, dpi: int = DEFAULT_PREVIEW_DPI):
    if side not in _PREVIEW_SIDES:
        raise HTTPException(status_code=400, detail="side must be 'source' or 'target'")
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be positive")
    task = tasks_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "done":
        raise HTTPException(status_code=409, detail="Preview is not ready")
    preview_dir = tasks_store.preview_dir(task_id)
    file = (
        tasks_store.source_path(task_id)
        if side == "source"
        else tasks_store.result_path(task_id, task.get("artifact", ""))
    )
    if file is None or not file.is_file():
        raise HTTPException(status_code=404, detail="Source file is not available")
    try:
        pages = cached_page_count(preview_dir, file, side)
    except Exception:  # noqa: BLE001 - preview must never break the API
        pages = 0
    if page > pages:
        raise HTTPException(status_code=404, detail="Page is out of range")
    data = cached_page_png(preview_dir, file, side, page - 1, dpi=min(dpi, MAX_PREVIEW_DPI))
    if data is None:
        raise HTTPException(status_code=404, detail="Не удалось отрисовать страницу")
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


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
    try:
        content = artifact_path.read_bytes()
    except OSError as error:
        raise HTTPException(status_code=500, detail="Не удалось подготовить файл") from error
    filename = task["filename"]
    ascii_name = filename.encode("ascii", "ignore").decode() or "converted"
    from urllib.parse import quote

    disposition = f"attachment; filename={ascii_name}; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=content,
        media_type=task["media_type"],
        headers={"Content-Disposition": disposition},
    )


def _output_path_for(workspace: ArtifactWorkspace, source_path: Path, source: DocFormat, target: DocFormat) -> Path:
    if source is DocFormat.PPTX and target is DocFormat.HTML:
        return workspace.artifact_path(f"{source_path.stem}-html")
    return workspace.artifact_path(f"{source_path.stem}{_OUTPUT_SUFFIXES[target]}")


@app.post("/api/convert/batch")
async def api_convert_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    target_format: str = Form(""),
    mode: str = Form("balanced"),
):
    try:
        conversion_mode = ConversionMode(mode)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not files:
        raise HTTPException(status_code=400, detail="Не передано ни одного файла")
    if len(files) > _BATCH_LIMIT:
        raise HTTPException(status_code=400, detail=f"Слишком много файлов: максимум {_BATCH_LIMIT}")
    executor = ConversionExecutor()
    workspaces: list[ArtifactWorkspace] = []
    prepared: list[tuple[ArtifactWorkspace, Path, DocFormat, DocFormat]] = []
    try:
        for upload in files:
            workspace = create_web_workspace()
            workspaces.append(workspace)
            source_path = await save_upload(workspace, upload, fallback="document")
            source, target = _resolve_conversion(source_path, source_format="auto", target_format=target_format, legacy_format="")
            if target not in _OUTPUT_SUFFIXES:
                raise HTTPException(status_code=400, detail=f"Формат результата {target.value} пока недоступен в Web UI")
            plan = executor.plan(source, target, mode=conversion_mode)
            if plan is None or not _web_plan_supported(plan):
                raise HTTPException(
                    status_code=400,
                    detail=f"Маршрут {source.value} → {target.value} ({conversion_mode.value}) недоступен",
                )
            prepared.append((workspace, source_path, source, target))
    except HTTPException:
        for workspace in workspaces:
            workspace.cleanup()
        raise

    tasks: list[dict[str, object]] = []
    for workspace, source_path, source, target in prepared:
        task_id = str(uuid.uuid4())
        _register_task(
            task_id,
            {
                "status": "running",
                "error": None,
                "report": None,
                "source_format": source.value,
                "target_format": target.value,
                "mode": conversion_mode.value,
            },
        )
        output_path = _output_path_for(workspace, source_path, source, target)
        background_tasks.add_task(
            _run_convert, task_id, source_path, output_path, source, target, conversion_mode, workspace, True
        )
        tasks.append(
            {
                "name": source_path.name,
                "task_id": task_id,
                "source_format": source.value,
                "target_format": target.value,
                "status": f"/api/convert/status/{task_id}",
                "result": f"/api/convert/result/{task_id}",
            }
        )
    job_id = str(uuid.uuid4())
    tasks_store.set_job(
        job_id,
        {
            "job_id": job_id,
            "target_format": target_format,
            "mode": conversion_mode.value,
            "files": tasks,
        },
    )
    return {"success": True, "job_id": job_id, "tasks": tasks}


@app.get("/api/convert/jobs")
async def api_convert_jobs():
    jobs = tasks_store.list_jobs(limit=_JOBS_HISTORY_LIMIT)
    result = []
    for job in jobs:
        files = job.get("files", [])
        counts = {"running": 0, "done": 0, "error": 0, "expired": 0}
        for item in files:
            task = tasks_store.get(item["task_id"])
            status = task["status"] if task else "expired"
            counts[status] = counts.get(status, 0) + 1
        result.append(
            {
                "job_id": job["job_id"],
                "created": job.get("_ts"),
                "target_format": job.get("target_format"),
                "mode": job.get("mode"),
                "files": [item["name"] for item in files],
                "counts": counts,
            }
        )
    return {"jobs": result}


@app.get("/api/convert/jobs/{job_id}")
async def api_convert_job(job_id: str):
    job = tasks_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    entries = []
    for item in job.get("files", []):
        task = tasks_store.get(item["task_id"])
        entry: dict[str, object] = {
            "name": item["name"],
            "task_id": item["task_id"],
            "status_url": item.get("status"),
            "result_url": item.get("result"),
        }
        if task is None:
            entry["status"] = "expired"
            entry["error"] = "Истёк срок хранения результата"
        else:
            entry.update(_public_task_payload(task))
        entries.append(entry)
    return {"job_id": job_id, "target_format": job.get("target_format"), "mode": job.get("mode"), "tasks": entries}


@app.delete("/api/convert/jobs/{job_id}")
async def api_convert_job_delete(job_id: str):
    job = tasks_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    for item in job.get("files", []):
        tasks_store.delete(item["task_id"])
    tasks_store.delete_job(job_id)
    return {"success": True, "job_id": job_id}


@app.post("/api/convert/jobs/{job_id}/rerun")
async def api_convert_job_rerun(job_id: str, background_tasks: BackgroundTasks):
    job = tasks_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        conversion_mode = ConversionMode(job["mode"])
    except (KeyError, ValueError):
        conversion_mode = ConversionMode.BALANCED
    executor = ConversionExecutor()
    workspaces: list[ArtifactWorkspace] = []
    launched: list[str] = []
    try:
        for item in job.get("files", []):
            task_id = item["task_id"]
            source_path = tasks_store.source_path(task_id)
            if source_path is None:
                continue
            source = DocFormat(item["source_format"])
            target = DocFormat(item["target_format"])
            plan = executor.plan(source, target, mode=conversion_mode)
            if plan is None or not _web_plan_supported(plan):
                continue
            workspace = create_web_workspace()
            workspaces.append(workspace)
            output_path = _output_path_for(workspace, source_path, source, target)
            _register_task(
                task_id,
                {
                    "status": "running",
                    "error": None,
                    "report": None,
                    "source_format": source.value,
                    "target_format": target.value,
                    "mode": conversion_mode.value,
                },
            )
            background_tasks.add_task(
                _run_convert, task_id, source_path, output_path, source, target, conversion_mode, workspace, False
            )
            launched.append(task_id)
    except HTTPException:
        for workspace in workspaces:
            workspace.cleanup()
        raise
    return {"success": True, "job_id": job_id, "launched": launched}
