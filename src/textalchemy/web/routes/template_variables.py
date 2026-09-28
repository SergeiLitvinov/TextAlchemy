"""Visual rename of simple template variables."""
from fastapi import HTTPException, Response
from pydantic import BaseModel, Field

from textalchemy.core.exceptions import GenerateError
from textalchemy.web.app import app
from textalchemy.web.routes.generate import resolve_web_template, template_schema_for
from textalchemy.web.services.template_conditions import condition_copy, inspect_conditions
from textalchemy.web.services.template_variables import inspect_variables, rename_copy


class RenameInput(BaseModel):
    old: str = Field(max_length=64)
    new: str = Field(max_length=64)
    revision: str = Field(max_length=64)


class ConditionInput(BaseModel):
    block: int = Field(ge=0)
    field: str = Field(min_length=1, max_length=64)
    negate: bool = False
    revision: str = Field(max_length=64)


@app.get('/api/generate/templates/{name}/conditions')
def conditions(name: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        path = resolve_web_template(name)
        if path.suffix.lower() != '.docx':
            raise ValueError('Редактор условий доступен для DOCX-шаблонов.')
        schema, _ = template_schema_for(name)
        return inspect_conditions(path.read_bytes(), schema.to_dict())
    except GenerateError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post('/api/generate/templates/{name}/conditions')
def save_condition(name: str, data: ConditionInput):
    try:
        path = resolve_web_template(name)
        if path.suffix.lower() != '.docx':
            raise ValueError('Редактор условий доступен для DOCX-шаблонов.')
        schema, _ = template_schema_for(name)
        result = condition_copy(path, schema.to_dict(), **data.model_dump())
        return {'name': result}
    except GenerateError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except OSError as error:
        raise HTTPException(503, 'Не удалось сохранить копию шаблона. Повторите попытку.') from error


@app.get('/api/generate/templates/{name}/variables')
def variables(name: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        path = resolve_web_template(name)
        if path.suffix.lower() != '.docx':
            raise ValueError('Редактор переменных доступен для DOCX-шаблонов.')
        schema, _ = template_schema_for(name)
        return inspect_variables(path.read_bytes(), schema.to_dict())
    except GenerateError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post('/api/generate/templates/{name}/variables')
def rename_variable(name: str, data: RenameInput):
    try:
        path = resolve_web_template(name)
        if path.suffix.lower() != '.docx':
            raise ValueError('Редактор переменных доступен для DOCX-шаблонов.')
        schema, _ = template_schema_for(name)
        result = rename_copy(path, schema.to_dict(), old=data.old, new=data.new, revision=data.revision)
        return {'name': result}
    except GenerateError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except OSError as error:
        raise HTTPException(503, 'Не удалось сохранить копию шаблона. Повторите попытку.') from error
