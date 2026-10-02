"""HTTP-адаптеры конструктора конвейеров и экспорта библиографии."""

from typing import Any

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from textalchemy.web.app import _bibliography_service, app
from textalchemy.web.services.pipeline_builder import parse_pipeline, pipeline_yaml, run_pipeline, validate_pipeline
from textalchemy.web.services.pipeline_files import pipeline_result, store_input
from textalchemy.web.workspace import create_web_workspace, save_upload


@app.post("/api/pipeline/run")
def api_pipeline_run(spec: str = Form(...)) -> dict[str, Any]:
    return run_pipeline(spec)


@app.post("/api/pipeline/files")
async def api_pipeline_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    with create_web_workspace() as workspace:
        path = await save_upload(workspace, file, fallback="input.txt")
        return store_input(path)


@app.get("/api/pipeline/results/{task_id}")
def api_pipeline_download(task_id: str) -> FileResponse:
    try:
        path = pipeline_result(task_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return FileResponse(path, filename=path.name)


@app.post("/api/pipeline/parse")
async def api_pipeline_parse(spec: str = Form(...)) -> dict[str, Any]:
    return parse_pipeline(spec)


@app.post("/api/pipeline/yaml")
async def api_pipeline_yaml(spec: str = Form(...)) -> dict[str, Any]:
    return pipeline_yaml(spec)


@app.post("/api/pipeline/validate")
async def api_pipeline_validate(spec: str = Form(...)) -> dict[str, Any]:
    return validate_pipeline(spec)


@app.get("/api/export/{fmt}")
async def api_export(fmt: str) -> Response:
    try:
        exported = _bibliography_service().export(fmt)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return Response(
        content=exported.content,
        media_type=exported.media_type,
        headers={"Content-Disposition": f"attachment; filename={exported.filename}"},
    )
