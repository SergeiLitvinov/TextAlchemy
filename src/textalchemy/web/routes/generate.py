"""API генерации документов по шаблонам (DocumentModel + TemplateSchema)."""
from __future__ import annotations

import base64
import json
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Form, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from textalchemy.core.document_model import FormulaFormat
from textalchemy.core.exceptions import GenerateError
from textalchemy.generate import generate_document, list_templates
from textalchemy.generate.model_template import (
    TemplateFormula,
    TemplateImage,
    generate_docx_template,
    generate_html_template,
    generate_pdf_template,
    inspect_document_template,
)
from textalchemy.generate.template import TemplateEngine
from textalchemy.generate.template_schema import (
    TemplateField,
    TemplateSchema,
    TemplateValueType,
    load_template_schema,
    validate_template_data,
)
from textalchemy.web.app import app
from textalchemy.web.preview import (
    DEFAULT_PREVIEW_DPI,
    MAX_PREVIEW_DPI,
    cached_page_count,
    cached_page_png,
)
from textalchemy.web.services.generated_preview import generated_result, prepare_draft_preview, store_generated_preview
from textalchemy.web.services.generator_datasets import DatasetStore, validate_snapshot
from textalchemy.web.services.ocr_drafts import DraftConflictError
from textalchemy.web.services.template_source import fill_text_package
from textalchemy.web.services.template_variables import custom_path, custom_templates
from textalchemy.web.workspace import create_web_workspace


class DatasetInput(BaseModel):
    template: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=80)
    snapshot: dict
    revision: int | None = Field(default=None, ge=1)


def _datasets():
    from textalchemy.web.app import data_dir

    return DatasetStore(data_dir)


@contextmanager
def _dataset_errors():
    try:
        yield
    except DraftConflictError as error:
        raise HTTPException(409, str(error)) from error
    except (LookupError, GenerateError) as error:
        raise HTTPException(404, str(error)) from error
    except (ValueError, TypeError) as error:
        raise HTTPException(422, str(error)) from error
    except (OSError, sqlite3.Error) as error:
        raise HTTPException(503, 'Хранилище наборов недоступно. Данные формы остаются на экране.') from error


@app.get('/api/generate/datasets')
def list_datasets(template: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    with _dataset_errors():
        return _datasets().list(template)


@app.get('/api/generate/datasets/{dataset_id}')
def get_dataset(dataset_id: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    with _dataset_errors():
        result = _datasets().get(dataset_id)
        schema, _ = template_schema_for(result['template'])
        validate_snapshot(result['snapshot'], schema.to_dict())
        return result


@app.post('/api/generate/datasets')
def create_dataset(data: DatasetInput):
    with _dataset_errors():
        if data.revision is not None:
            raise ValueError('Новый набор не должен иметь ревизию')
        schema, _ = template_schema_for(data.template)
        validate_snapshot(data.snapshot, schema.to_dict())
        return _datasets().save(template=data.template, name=data.name, snapshot=data.snapshot)


@app.put('/api/generate/datasets/{dataset_id}')
def update_dataset(dataset_id: str, data: DatasetInput):
    with _dataset_errors():
        if data.revision is None:
            raise ValueError('Для обновления нужна ревизия загруженного набора')
        schema, _ = template_schema_for(data.template)
        validate_snapshot(data.snapshot, schema.to_dict())
        return _datasets().save(template=data.template, name=data.name, snapshot=data.snapshot,
                                dataset_id=dataset_id, revision=data.revision)

_MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
}
_FORMAT_SUFFIX = {"docx": ".docx", "html": ".html", "pdf": ".pdf"}


def resolve_web_template(name: str, templates_dir: str | Path | None = None) -> Path:
    return custom_path(name) if name.startswith('edited-') else TemplateEngine(templates_dir).resolve_template(name)


def template_schema_for(name: str, templates_dir: str | Path | None = None) -> tuple[TemplateSchema, str]:
    """Вернуть (схема, источник) для шаблона: sidecar-файл или авто-деривация."""
    template_path = resolve_web_template(name, templates_dir)
    stem = template_path.stem
    for suffix in (".json", ".yaml", ".yml", ".toml"):
        sidecar = template_path.with_name(f"{stem}.schema{suffix}")
        if sidecar.is_file():
            return load_template_schema(sidecar), "sidecar"
    if template_path.suffix.lower() == ".docx":
        from textalchemy.formats.docx import read_docx_model

        model = read_docx_model(template_path)
        inspection = inspect_document_template(model)
        fields = [
            TemplateField(variable, TemplateValueType.STRING, required=False, description="")
            for variable in inspection.required_variables
        ]
        return TemplateSchema(fields=fields, allow_extra=True), "derived"
    return TemplateSchema(fields=[], allow_extra=True), "derived"


def _parse_validation_errors(message: str) -> dict[str, str]:
    """Разобрать сообщение GenerateError в карту {поле: ошибка}."""
    errors: dict[str, str] = {}
    for line in message.splitlines():
        line = line.strip()
        if line.startswith("- "):
            line = line[2:]
        if ": " in line:
            field, _, detail = line.partition(": ")
            errors.setdefault(field, detail)
    return errors


def _decode_data_uri(uri: str) -> TemplateImage:
    header, _, payload = uri.partition(",")
    media_type = header.removeprefix("data:").split(";")[0] or "image/png"
    return TemplateImage(data=base64.b64decode(payload), media_type=media_type, filename="upload")


def _prepare_web_params(schema: TemplateSchema, params: dict) -> dict:
    """Заменить data-URI изображений на TemplateImage до валидации."""
    result = dict(params)
    for field in schema.fields:
        if field.type is TemplateValueType.FORMULA:
            value = result.get(field.name)
            if isinstance(value, str) and value.lstrip().startswith('<math'):
                result[field.name] = TemplateFormula(value=value, format=FormulaFormat.MATHML)
        if field.type is not TemplateValueType.IMAGE:
            continue
        value = result.get(field.name)
        if isinstance(value, str) and value.startswith("data:"):
            result[field.name] = _decode_data_uri(value)
    return result


def _output_name(name: str, fmt: str) -> str:
    stem = Path(name).stem or "output"
    return f"{stem}{_FORMAT_SUFFIX[fmt]}"


def _template_preview_dir(name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return Path(tempfile.gettempdir()) / "textalchemy_generate_preview" / safe


@app.get("/api/generate/templates")
async def api_list_templates():
    templates_list = list_templates()
    return [
        {"name": t.name, "description": t.description, "template_type": t.template_type}
        for t in templates_list
    ] + custom_templates()


@app.get("/api/generate/templates/{name}/schema")
async def api_generate_template_schema(name: str):
    try:
        schema, source = template_schema_for(name)
    except GenerateError as error:
        raise HTTPException(status_code=404, detail=str(error))
    description = next((t.description for t in list_templates() if t.name == name),
                       next((t['description'] for t in custom_templates() if t['name'] == name), name))
    return {"name": name, "description": description, "source": source, "schema": schema.to_dict()}


@app.get("/api/generate/templates/{name}/preview/meta")
def api_generate_template_preview_meta(name: str):
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
def api_generate_template_preview(name: str, page: int = 1, dpi: int = DEFAULT_PREVIEW_DPI):
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


@app.post("/api/generate")
def api_generate(
    background_tasks: BackgroundTasks,
    template: str = Form(...),
    output: str = Form("output.docx"),
    format: str = Form("docx"),
    params: str = Form("{}"),
    preview: bool = Form(False),
):
    fmt = format if format in _MEDIA_TYPES else "docx"
    try:
        parsed = json.loads(params) if params else {}
    except json.JSONDecodeError as error:
        return {"success": False, "error": f"Некорректный JSON параметров: {error}"}
    try:
        schema, _ = template_schema_for(template)
    except GenerateError as error:
        return {"success": False, "error": str(error)}
    try:
        prepared = _prepare_web_params(schema, parsed)
        missing = []
        if preview:
            validated, schema, missing = prepare_draft_preview(schema, prepared)
        else:
            validated = validate_template_data(schema, prepared)
    except GenerateError as error:
        return {"success": False, "errors": _parse_validation_errors(str(error)), "error": str(error)}

    workspace = create_web_workspace()
    if missing:
        output = 'Черновик — ' + Path(output).name
    out_path = workspace.artifact_path(_output_name(Path(output).name, fmt), fallback=f"output{_FORMAT_SUFFIX[fmt]}")
    try:
        template_path = resolve_web_template(template)
        if template_path.suffix.lower() == ".docx":
            if fmt == "html":
                report = generate_html_template(template_path, out_path, validated, strict=True, schema=schema)
            elif fmt == "pdf":
                report = generate_pdf_template(template_path, out_path, validated, strict=True, schema=schema)
            elif fill_text_package(template_path, out_path, validated):
                report = None
            else:
                report = generate_docx_template(template_path, out_path, validated, strict=True, schema=schema)
            result = report.output_path if report else out_path
        else:
            if fmt != "docx":
                raise ValueError("Формат HTML/PDF доступен только для DOCX-шаблонов")
            generate_document(template, out_path, validated)
            result = out_path
        workspace.validate_artifact(result)
        if preview:
            try:
                return {**store_generated_preview(result, fmt), 'draft': bool(missing), 'missing_fields': missing}
            finally:
                workspace.cleanup()
        background_tasks.add_task(workspace.cleanup)
        return FileResponse(str(result), filename=result.name, media_type=_MEDIA_TYPES[fmt])
    except Exception as error:  # noqa: BLE001
        workspace.cleanup()
        return {"success": False, "error": str(error)}


@app.get('/api/generate/results/{task_id}')
def api_generated_result(task_id: str):
    try:
        task, path, _ = generated_result(task_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return FileResponse(path, filename=task['filename'], media_type=_MEDIA_TYPES[task['target_format']])


@app.get('/api/generate/results/{task_id}/pages/{page}')
def api_generated_page(task_id: str, page: int):
    try:
        _, path, directory = generated_result(task_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    data = cached_page_png(directory, path, 'result', page - 1, dpi=DEFAULT_PREVIEW_DPI) if page > 0 else None
    if data is None:
        raise HTTPException(404, 'Страница результата недоступна')
    return Response(data, media_type='image/png', headers={'Cache-Control': 'no-store'})
