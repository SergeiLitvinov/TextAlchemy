"""Web API конвертации через единый capability planner."""

from __future__ import annotations

import base64
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest, infer_format
from textalchemy.core.conversion_graph import ConversionPlan
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.types import DocFormat
from textalchemy.web.app import _register_task, _tasks, app

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


def _artifact_payload(output_path: Path, source_stem: str, target: DocFormat) -> tuple[bytes, str, str]:
    if output_path.is_dir():
        archive_base = output_path.parent / f"{source_stem}-html"
        archive = Path(shutil.make_archive(str(archive_base), "zip", output_path))
        return archive.read_bytes(), archive.name, "application/zip"
    return output_path.read_bytes(), output_path.name, _MEDIA_TYPES[target]


def _web_plan_supported(plan: ConversionPlan) -> bool:
    """Web executor safely supports direct routes and intermediate DocumentModel values."""

    return all(step.target is DocFormat.MODEL for step in plan.steps[:-1])


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
) -> None:
    workdir = source_path.parent
    try:
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
            _register_task(task_id, {"status": "error", "error": error, "report": report_payload})
            return
        content, filename, media_type = _artifact_payload(output_path, source_path.stem, target)
        _register_task(
            task_id,
            {
                "status": "done",
                "content": base64.b64encode(content).decode("ascii"),
                "filename": filename,
                "media_type": media_type,
                "error": None,
                "report": report_payload,
            },
        )
    except Exception as error:  # noqa: BLE001 - background task must expose a stable status
        _register_task(task_id, {"status": "error", "error": str(error), "report": None})
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@app.get("/api/convert/capabilities")
async def api_convert_capabilities():
    return _available_conversions(ConversionExecutor())


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
    workdir = Path(tempfile.mkdtemp(prefix="textalchemy_web_"))
    source_path = workdir / Path(file.filename or "document").name
    source_path.write_bytes(await file.read())
    try:
        source, target = _resolve_conversion(
            source_path,
            source_format=source_format,
            target_format=target_format,
            legacy_format=fmt,
        )
        conversion_mode = ConversionMode(mode)
    except ValueError as error:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(error)) from error

    plan = ConversionExecutor().plan(source, target, mode=conversion_mode)
    if plan is None or not _web_plan_supported(plan):
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(
            status_code=400,
            detail=f"Маршрут {source.value} → {target.value} ({conversion_mode.value}) недоступен",
        )

    if target not in _OUTPUT_SUFFIXES:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Формат результата {target.value} пока недоступен в Web UI")
    output_path = (
        workdir / f"{source_path.stem}-html"
        if source is DocFormat.PPTX and target is DocFormat.HTML
        else workdir / f"{source_path.stem}{_OUTPUT_SUFFIXES[target]}"
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
    background_tasks.add_task(_run_convert, task_id, source_path, output_path, source, target, conversion_mode)
    return {
        "success": True,
        "task_id": task_id,
        "status": f"/api/convert/status/{task_id}",
        "result": f"/api/convert/result/{task_id}",
    }


@app.get("/api/convert/status/{task_id}")
async def api_convert_status(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        key: value
        for key, value in task.items()
        if key not in {"content", "_ts", "media_type", "filename"}
    } | ({"filename": task["filename"]} if task.get("filename") else {})


@app.get("/api/convert/result/{task_id}")
async def api_convert_result(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "done":
        raise HTTPException(status_code=409, detail="Result is not ready")
    try:
        content = base64.b64decode(task["content"], validate=True)
    except (KeyError, ValueError) as error:
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
