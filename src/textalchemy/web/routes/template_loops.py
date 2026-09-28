"""Маршруты правки повторяемого абзаца шаблона."""
from fastapi import HTTPException, Response
from pydantic import BaseModel, Field

from textalchemy.core.exceptions import GenerateError
from textalchemy.web.app import app
from textalchemy.web.routes.generate import resolve_web_template, template_schema_for
from textalchemy.web.services.template_loops import inspect_loops, loop_copy
from textalchemy.web.services.template_rows import inspect_rows, row_copy


class LoopInput(BaseModel):
    block: int = Field(ge=0)
    variable: str = Field(min_length=1, max_length=64)
    field: str = Field(min_length=1, max_length=64)
    revision: str = Field(max_length=64)


class RowInput(LoopInput):
    block: str = Field(pattern=r'^\d+:\d+$')


@app.get('/api/generate/templates/{name}/table-loops')
def table_loops(name: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        path, schema = _source(name)
        return inspect_rows(path.read_bytes(), schema)
    except GenerateError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post('/api/generate/templates/{name}/table-loops')
def save_table_loop(name: str, data: RowInput):
    try:
        path, schema = _source(name)
        return {'name': row_copy(path, schema, **data.model_dump())}
    except GenerateError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except OSError as error:
        raise HTTPException(503, 'Не удалось сохранить копию шаблона.') from error


def _source(name):
    path = resolve_web_template(name)
    if path.suffix.lower() != '.docx':
        raise ValueError('Редактор цикла доступен для DOCX-шаблонов.')
    schema, _ = template_schema_for(name)
    return path, schema.to_dict()


@app.get('/api/generate/templates/{name}/loops')
def loops(name: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        path, schema = _source(name)
        return inspect_loops(path.read_bytes(), schema)
    except GenerateError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post('/api/generate/templates/{name}/loops')
def save_loop(name: str, data: LoopInput):
    try:
        path, schema = _source(name)
        return {'name': loop_copy(path, schema, **data.model_dump())}
    except GenerateError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except OSError as error:
        raise HTTPException(503, 'Не удалось сохранить копию шаблона.') from error
