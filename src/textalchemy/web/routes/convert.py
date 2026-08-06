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
) -> None:
    source_inspection = None
    inspection_error = None
    try:
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
    background_tasks.add_task(_run_convert, task_id, source_path, output_path, source, target, conversion_mode, workspace)
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
    return {
        key: value
        for key, value in task.items()
        if key not in {"artifact", "content", "_ts", "media_type", "filename"}
    } | ({"filename": task["filename"]} if task.get("filename") else {})


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
