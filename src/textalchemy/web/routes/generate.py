"""API генерации документов по шаблонам."""
from __future__ import annotations

from fastapi import Form

from textalchemy.generate import generate_document, list_templates
from textalchemy.web.app import app


@app.get("/api/generate/templates")
async def api_list_templates():
    templates_list = list_templates()
    return [{"name": t.name, "description": t.description} for t in templates_list]


@app.post("/api/generate")
async def api_generate(
    template: str = Form(...),
    output: str = Form("output.docx"),
    params: str = Form("{}"),
):
    import json

    try:
        result = generate_document(template, output, json.loads(params))
        return {"success": True, "path": result}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
