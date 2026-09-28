"""Import a DOCX sample and explicitly select linked replacement occurrences."""
import json
import re

from fastapi import File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from textalchemy.core.exceptions import GenerateError
from textalchemy.generate.template_schema import TemplateSchema
from textalchemy.web.app import app
from textalchemy.web.routes.generate import resolve_web_template, template_schema_for
from textalchemy.web.services.template_rich import rich_copy
from textalchemy.web.services.template_source import checked_docx, field_copy, inspect_source
from textalchemy.web.services.template_variables import save_template_copy
from textalchemy.web.workspace import create_web_workspace, save_upload


class Occurrence(BaseModel):
    id: str = Field(max_length=150)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class SourceField(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    label: str = Field(min_length=1, max_length=100)
    selected: list[Occurrence] = Field(min_length=1, max_length=2000)
    expected: str = Field(max_length=64)


class RichField(BaseModel):
    block: str = Field(max_length=150)
    kind: str = Field(pattern='^(image|formula|bibliography|id|ref)$')
    field: str = Field(min_length=1, max_length=64)
    expected: str = Field(max_length=64)


@app.post('/api/generate/templates/{name}/rich')
def save_rich_field(name: str, data: RichField):
    try:
        path = resolve_web_template(name)
        schema, _ = template_schema_for(name)
        return {'name': rich_copy(path, schema.to_dict(), **data.model_dump())}
    except GenerateError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post('/api/generate/import')
async def import_template(file: UploadFile = File(...), field_schema: str = Form('', alias='schema')):
    try:
        if not (file.filename or '').lower().endswith('.docx'):
            raise ValueError('Выберите файл DOCX.')
        with create_web_workspace() as workspace:
            path = await save_upload(workspace, file, fallback='sample.docx')
            data = path.read_bytes()
            checked_docx(data)
            if field_schema:
                raw_schema = json.loads(field_schema)
                if not isinstance(raw_schema, dict):
                    raise ValueError('Схема должна быть объектом с полями fields.')
                definition = TemplateSchema.from_dict(raw_schema)
                names = [field.name for field in definition.fields]
                if (len(set(names)) != len(names) or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', n) for n in names)):
                    raise ValueError('Для Web нужны уникальные одноуровневые имена полей латиницей.')
            else:
                from textalchemy.formats.docx import read_docx_model
                from textalchemy.generate.model_template import inspect_document_template
                from textalchemy.generate.template_schema import TemplateField, TemplateValueType

                inspection = inspect_document_template(read_docx_model(path))
                if not inspection.valid:
                    raise ValueError('; '.join(inspection.errors))
                definition = TemplateSchema(fields=[TemplateField(name, TemplateValueType.STRING, required=False)
                    for name in inspection.required_variables])
            name = save_template_copy(data, definition.to_dict())
            return {'name': name}
    except (ValueError, KeyError, TypeError, GenerateError) as error:
        raise HTTPException(422, str(error)) from error


@app.get('/api/generate/templates/{name}/source')
def source_template(name: str, query: str = Query('', max_length=2000)):
    try:
        path = resolve_web_template(name)
        schema, _ = template_schema_for(name)
        return inspect_source(path.read_bytes(), schema.to_dict(), query)
    except GenerateError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post('/api/generate/templates/{name}/source')
def save_source_field(name: str, data: SourceField):
    try:
        path = resolve_web_template(name)
        schema, _ = template_schema_for(name)
        return {'name': field_copy(path, schema.to_dict(), **data.model_dump())}
    except GenerateError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
