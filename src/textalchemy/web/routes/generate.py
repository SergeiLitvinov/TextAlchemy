"""API генерации документов по шаблонам."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from fastapi import BackgroundTasks, Form
from fastapi.responses import FileResponse

from textalchemy.generate import generate_document, list_templates
from textalchemy.web.app import app


@app.get("/api/generate/templates")
async def api_list_templates():
    templates_list = list_templates()
    return [{"name": t.name, "description": t.description} for t in templates_list]


@app.post("/api/generate")
async def api_generate(
    background_tasks: BackgroundTasks,
    template: str = Form(...),
    output: str = Form("output.docx"),
    params: str = Form("{}"),
):
    try:
        parsed = json.loads(params) if params else {}
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Некорректный JSON параметров: {e}"}
    workdir = Path(tempfile.mkdtemp(prefix="textalchemy_web_"))
    out_path = workdir / Path(output).name
    try:
        result = generate_document(template, out_path, parsed)
        background_tasks.add_task(shutil.rmtree, workdir, ignore_errors=True)
        return FileResponse(
            str(result),
            filename=out_path.name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(workdir, ignore_errors=True)
        return {"success": False, "error": str(e)}
