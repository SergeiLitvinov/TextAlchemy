"""API генерации документов по шаблонам."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import BackgroundTasks, Form
from fastapi.responses import FileResponse

from textalchemy.generate import generate_document, list_templates
from textalchemy.web.app import app
from textalchemy.web.workspace import create_web_workspace


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
    workspace = create_web_workspace()
    out_path = workspace.artifact_path(Path(output).name, fallback="output.docx")
    try:
        result = generate_document(template, out_path, parsed)
        workspace.validate_artifact(result)
        background_tasks.add_task(workspace.cleanup)
        return FileResponse(
            str(result),
            filename=out_path.name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    except Exception as e:  # noqa: BLE001
        workspace.cleanup()
        return {"success": False, "error": str(e)}
