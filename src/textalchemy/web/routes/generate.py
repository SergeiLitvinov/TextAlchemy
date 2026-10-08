"""API генерации документов по шаблонам (DocumentModel + TemplateSchema)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import BackgroundTasks, Form, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from textalchemy.core.exceptions import GenerateError
from textalchemy.generate import list_templates
from textalchemy.web.app import app
from textalchemy.web.preview import (
    DEFAULT_PREVIEW_DPI,
    MAX_PREVIEW_DPI,
    cached_page_count,
    cached_page_png,
)
from textalchemy.web.services.generated_preview import generated_result, store_generated_preview
from textalchemy.web.services.generator_catalog import (
    MEDIA_TYPES as _MEDIA_TYPES,
)
from textalchemy.web.services.generator_catalog import (
    GeneratorCatalogService,
    _template_preview_dir,
)
from textalchemy.web.services.generator_catalog import (
    _decode_data_uri as _decode_data_uri,
)
from textalchemy.web.services.generator_catalog import (
    _prepare_web_params as _prepare_web_params,
)
from textalchemy.web.services.generator_catalog import (
    resolve_web_template as resolve_web_template,
)
from textalchemy.web.services.generator_catalog import (
    template_schema_for as template_schema_for,
)
from textalchemy.web.services.generator_datasets import DatasetStore
from textalchemy.web.services.generator_execution import (
    GeneratedFile,
    GeneratorService,
)
from textalchemy.web.services.generator_execution import (
    generate_document as generate_document,
)
from textalchemy.web.services.generator_execution import (
    generate_docx_template as generate_docx_template,
)
from textalchemy.web.services.generator_execution import (
    generate_html_template as generate_html_template,
)
from textalchemy.web.services.generator_execution import (
    generate_pdf_template as generate_pdf_template,
)
from textalchemy.web.services.generator_sessions import GeneratorDatasetService
from textalchemy.web.services.live_preview import LivePreviewService
from textalchemy.web.services.ocr_drafts import DraftConflictError
from textalchemy.web.services.template_source import fill_text_package
from textalchemy.web.services.template_variables import custom_templates
from textalchemy.web.workspace import create_web_workspace


class DatasetInput(BaseModel):
    template: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=80)
    snapshot: dict[str, Any]
    revision: int | None = Field(default=None, ge=1)


def _datasets() -> GeneratorDatasetService:
    from textalchemy.web.app import data_dir

    return GeneratorDatasetService(DatasetStore(data_dir), template_schema_for)


@contextmanager
def _dataset_errors() -> Iterator[None]:
    try:
        yield
    except DraftConflictError as error:
        raise HTTPException(409, str(error)) from error
    except (LookupError, GenerateError) as error:
        raise HTTPException(404, str(error)) from error
    except (ValueError, TypeError) as error:
        raise HTTPException(422, str(error)) from error
    except (OSError, sqlite3.Error) as error:
        raise HTTPException(503, "Хранилище наборов недоступно. Данные формы остаются на экране.") from error


@app.get("/api/generate/datasets")
def list_datasets(template: str, response: Response) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = "no-store"
    with _dataset_errors():
        return _datasets().list(template)


@app.get("/api/generate/datasets/{dataset_id}")
def get_dataset(dataset_id: str, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    with _dataset_errors():
        return _datasets().get(dataset_id)


@app.post("/api/generate/datasets")
def create_dataset(data: DatasetInput) -> dict[str, Any]:
    with _dataset_errors():
        return _datasets().save(template=data.template, name=data.name, snapshot=data.snapshot, revision=data.revision)


@app.put("/api/generate/datasets/{dataset_id}")
def update_dataset(dataset_id: str, data: DatasetInput) -> dict[str, Any]:
    with _dataset_errors():
        return _datasets().save(
            template=data.template, name=data.name, snapshot=data.snapshot, dataset_id=dataset_id, revision=data.revision
        )


@app.get("/api/generate/templates")
async def api_list_templates() -> list[dict[str, Any]]:
    return GeneratorCatalogService(list_templates, custom_templates, template_schema_for).list()


@app.get("/api/generate/templates/{name}/schema")
async def api_generate_template_schema(name: str) -> dict[str, Any]:
    try:
        return GeneratorCatalogService(list_templates, custom_templates, template_schema_for).schema(name)
    except GenerateError as error:
        raise HTTPException(status_code=404, detail=str(error))


@app.get("/api/generate/templates/{name}/preview/meta")
def api_generate_template_preview_meta(name: str) -> dict[str, Any]:
    try:
        template_path = resolve_web_template(name)
    except GenerateError as error:
        raise HTTPException(status_code=404, detail=str(error))
    preview_dir = _template_preview_dir(name)
    try:
        pages = cached_page_count(preview_dir, template_path, "template")
    except Exception as error:  # noqa: BLE001 - preview must never break the API
        return {"available": False, "pages": 0, "error": str(error)}
    return {"available": pages > 0, "pages": pages, "error": None}


@app.get("/api/generate/templates/{name}/preview")
def api_generate_template_preview(name: str, page: int = 1, dpi: int = DEFAULT_PREVIEW_DPI) -> Response:
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be positive")
    try:
        template_path = resolve_web_template(name)
    except GenerateError as error:
        raise HTTPException(status_code=404, detail=str(error))
    preview_dir = _template_preview_dir(name)
    data = cached_page_png(preview_dir, template_path, "template", page - 1, dpi=min(dpi, MAX_PREVIEW_DPI))
    if data is None:
        raise HTTPException(status_code=404, detail="Превью недоступно")
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/generate", response_model=None)
def api_generate(
    background_tasks: BackgroundTasks,
    template: str = Form(...),
    output: str = Form("output.docx"),
    format: str = Form("docx"),
    params: str = Form("{}"),
    preview: bool = Form(False),
) -> Response | dict[str, Any]:
    service = GeneratorService(
        store_generated_preview=store_generated_preview,
        schema_provider=template_schema_for,
        resolve_template=resolve_web_template,
        workspace_factory=create_web_workspace,
        generate_docx_template=generate_docx_template,
        generate_html_template=generate_html_template,
        generate_pdf_template=generate_pdf_template,
        fill_text_package=fill_text_package,
        generate_document=generate_document,
    )
    result = service.generate(template=template, output=output, format=format, params=params, preview=preview)
    if isinstance(result, GeneratedFile):
        background_tasks.add_task(result.cleanup)
        return FileResponse(result.path, filename=result.path.name, media_type=result.media_type)
    return result


@app.post("/api/generate/live-preview")
def api_generate_live_preview(
    template: str = Form(...), params: str = Form("{}"), source: bool = Form(False)
) -> dict[str, Any]:
    """Черновой HTML для заполнения или чтения исходника без офисного движка."""
    return LivePreviewService(workspace_factory=create_web_workspace).preview(template=template, params=params, source=source)


@app.get("/api/generate/results/{task_id}")
def api_generated_result(task_id: str) -> FileResponse:
    try:
        task, path, _ = generated_result(task_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return FileResponse(path, filename=task["filename"], media_type=_MEDIA_TYPES[task["target_format"]])


@app.get("/api/generate/results/{task_id}/pages/{page}")
def api_generated_page(task_id: str, page: int) -> Response:
    try:
        _, path, directory = generated_result(task_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    data = cached_page_png(directory, path, "result", page - 1, dpi=DEFAULT_PREVIEW_DPI) if page > 0 else None
    if data is None:
        raise HTTPException(404, "Страница результата недоступна")
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})
