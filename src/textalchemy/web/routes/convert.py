"""API конвертации (PDF→DOCX, PPTX→HTML) через фоновые задачи."""
from __future__ import annotations

import base64
import shutil
import tempfile
import uuid

from fastapi import BackgroundTasks, File, Form, UploadFile
from fastapi.responses import Response

from textalchemy.convert.pdf_to_docx import create_converter
from textalchemy.web.app import _register_task, _tasks, app


def _run_convert(task_id: str, src_path, out_path, tool: str, fmt: str):
    workdir = src_path.parent
    if fmt == "pptx":
        try:
            from textalchemy.convert.pptx_to_html import convert as pptx_to_html

            out_dir = tempfile.mkdtemp()
            try:
                pptx_to_html(src_path, out_dir)
                zip_path = out_path.with_suffix(".zip")
                shutil.make_archive(str(zip_path.with_suffix("")), "zip", out_dir)
                content = zip_path.read_bytes()
                _register_task(task_id, {
                    "status": "done",
                    "content": base64.b64encode(content).decode(),
                    "filename": src_path.stem + ".zip",
                    "error": None,
                })
                zip_path.unlink(missing_ok=True)
            finally:
                shutil.rmtree(out_dir, ignore_errors=True)
        except Exception as e:  # noqa: BLE001
            _register_task(task_id, {"status": "error", "error": str(e)})
        finally:
            src_path.unlink(missing_ok=True)
            shutil.rmtree(workdir, ignore_errors=True)
        return

    try:
        converter = create_converter(tool)
        result = converter.convert(src_path, out_path)
        if result.success:
            content = out_path.read_bytes()
            _register_task(task_id, {
                "status": "done",
                "content": base64.b64encode(content).decode(),
                "filename": out_path.name,
                "error": None,
            })
        else:
            _register_task(task_id, {"status": "error", "error": result.error})
    except Exception as e:  # noqa: BLE001
        _register_task(task_id, {"status": "error", "error": str(e)})
    finally:
        src_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)
        shutil.rmtree(workdir, ignore_errors=True)


@app.post("/api/convert")
async def api_convert(background_tasks: BackgroundTasks, file: UploadFile = File(...),
                      tool: str = Form("fanout"), fmt: str = Form("pdf")):
    tmp_dir = tempfile.mkdtemp()
    from pathlib import Path

    fname = file.filename or f"document.{fmt}"
    src = Path(tmp_dir) / fname
    src.write_bytes(await file.read())

    if fmt == "pptx":
        out = Path(tmp_dir) / (src.stem + ".zip")
    else:
        out = Path(tmp_dir) / (src.stem + ".docx")

    task_id = str(uuid.uuid4())
    _register_task(task_id, {"status": "running", "error": None})
    background_tasks.add_task(_run_convert, task_id, src, out, tool, fmt)
    return {"success": True, "task_id": task_id, "status": "/api/convert/status/" + task_id}


@app.get("/api/convert/status/{task_id}")
async def api_convert_status(task_id: str):
    from fastapi import HTTPException

    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] == "done":
        content = base64.b64decode(task["content"])
        fname = task["filename"]
        media_type = (
            "application/zip" if fname.endswith(".zip")
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    return {"status": task["status"], "error": task.get("error")}
