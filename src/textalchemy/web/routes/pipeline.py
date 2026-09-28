"""API запуска pipeline, синхронизации конструктора и экспорта."""
from __future__ import annotations

import io
import json
from typing import Any

import yaml
from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from textalchemy.core.registry import get
from textalchemy.pipeline import register_builtin_operations
from textalchemy.pipeline.render import render_bibtex, render_gost, render_json, render_markdown
from textalchemy.web.app import app, db
from textalchemy.web.services.pipeline_files import execute_web_pipeline, pipeline_result, store_input
from textalchemy.web.workspace import create_web_workspace, save_upload

_STEP_KEYS = ("steps", "output")


def _parse_spec(spec: str) -> dict[str, Any]:
    try:
        value = json.loads(spec)
    except json.JSONDecodeError:
        try:
            value = yaml.safe_load(spec)
        except yaml.YAMLError as error:
            raise ValueError(f"Некорректный YAML/JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("Pipeline spec должен быть объектом (dict)")
    return value


def _normalize_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Разложить spec на шаги, итоговый output и начальный контекст."""
    steps = []
    for index, step in enumerate(spec.get("steps") or []):
        if not isinstance(step, dict):
            continue
        steps.append({
            "index": index,
            "op": step.get("op", ""),
            "output": step.get("output", ""),
            "input": step.get("input", ""),
            "params": step.get("params") or {},
        })
    ctx = {key: value for key, value in spec.items() if key not in _STEP_KEYS}
    return {"steps": steps, "output": spec.get("output", ""), "ctx": ctx}


def _validate_spec(spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    known = set(key for key in spec if key not in _STEP_KEYS)
    outputs: set[str] = set()
    steps = spec.get("steps") or []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append({"step": index, "message": "шаг должен быть объектом"})
            continue
        op_id = step.get("op")
        if not op_id:
            errors.append({"step": index, "message": "missing 'op'"})
            continue
        try:
            get(op_id)
        except KeyError as error:
            errors.append({"step": index, "message": str(error)})
            continue
        output = step.get("output") or f"step{index}"
        if output in outputs:
            errors.append({"step": index, "message": f"дублируется имя вывода {output!r}"})
        outputs.add(output)
        input_name = step.get("input")
        if input_name and input_name not in known:
            errors.append({"step": index, "message": f"вход {input_name!r} не определён"})
        known.add(output)
    final_output = spec.get("output")
    if final_output and final_output not in known:
        errors.append({"step": None, "message": f"итоговый output {final_output!r} не определён"})
    if not steps:
        warnings.append("В пайплайне нет шагов")
    return errors, warnings


@app.post("/api/pipeline/run")
def api_pipeline_run(spec: str = Form(...)):
    register_builtin_operations()
    try:
        pipeline_def = _parse_spec(spec)
    except ValueError as error:
        return {"success": False, "error": str(error)}
    try:
        return execute_web_pipeline(pipeline_def)
    except (ValueError, KeyError, TypeError, OSError) as error:
        return {'success': False, 'error': str(error)}


@app.post('/api/pipeline/files')
async def api_pipeline_upload(file: UploadFile = File(...)):
    with create_web_workspace() as workspace:
        path = await save_upload(workspace, file, fallback='input.txt')
        return store_input(path)


@app.get('/api/pipeline/results/{task_id}')
def api_pipeline_download(task_id: str):
    try:
        path = pipeline_result(task_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return FileResponse(path, filename=path.name)


@app.post("/api/pipeline/parse")
async def api_pipeline_parse(spec: str = Form(...)):
    """Разобрать YAML/JSON в нормализованную структуру для визуального конструктора."""
    try:
        pipeline_def = _parse_spec(spec)
    except ValueError as error:
        return {"success": False, "error": str(error)}
    return {"success": True, "spec": _normalize_spec(pipeline_def)}


@app.post("/api/pipeline/yaml")
async def api_pipeline_yaml(spec: str = Form(...)):
    """Сериализовать (JSON или YAML) spec в канонический YAML для экспертного режима."""
    try:
        pipeline_def = _parse_spec(spec)
    except ValueError as error:
        return {"success": False, "error": str(error)}
    buffer = io.StringIO()
    yaml.safe_dump(pipeline_def, buffer, allow_unicode=True, sort_keys=False)
    return {"success": True, "yaml": buffer.getvalue()}


@app.post("/api/pipeline/validate")
async def api_pipeline_validate(spec: str = Form(...)):
    """Проверить связи шагов без выполнения пайплайна."""
    register_builtin_operations()
    try:
        pipeline_def = _parse_spec(spec)
    except ValueError as error:
        return {"success": False, "errors": [{"step": None, "message": str(error)}], "warnings": []}
    errors, warnings = _validate_spec(pipeline_def)
    return {"success": not errors, "errors": errors, "warnings": warnings}


@app.get("/api/export/{fmt}")
async def api_export(fmt: str):
    items = db.all_items()
    if fmt == "json":
        content = render_json(items=items)
        media_type = "application/json"
        filename = "bibliography.json"
    elif fmt == "markdown":
        content = render_markdown(items=items)
        media_type = "text/markdown"
        filename = "bibliography.md"
    elif fmt == "gost":
        content = render_gost(items=items)
        media_type = "text/plain; charset=utf-8"
        filename = "bibliography_gost.txt"
    elif fmt == "bibtex":
        content = render_bibtex(items=items)
        media_type = "application/x-bibtex"
        filename = "bibliography.bib"
    elif fmt == "ris":
        lines = []
        for it in items:
            au = it.authors if hasattr(it, "authors") else []
            title = it.title if hasattr(it, "title") else ""
            year = str(it.year) if hasattr(it, "year") and it.year else ""
            dt = it.doc_type if hasattr(it, "doc_type") else "GEN"
            for a in au:
                lines.append(f"AU  - {a}")
            lines.append(f"TI  - {title}")
            lines.append(f"PY  - {year}")
            lines.append(f"TY  - {dt.upper()[:4]}")
            lines.append("ER  -")
            lines.append("")
        content = "\n".join(lines)
        media_type = "application/x-research-info-systems"
        filename = "bibliography.ris"
    elif fmt == "csv":
        import csv

        buffer = io.StringIO()
        w = csv.writer(buffer)
        w.writerow(["id", "authors", "title", "year", "doc_type", "source"])
        for it in items:
            w.writerow([
                getattr(it, "index", ""),
                "; ".join(getattr(it, "authors", [])),
                getattr(it, "title", ""),
                getattr(it, "year", ""),
                getattr(it, "doc_type", ""),
                getattr(it, "source", ""),
            ])
        content = buffer.getvalue()
        media_type = "text/csv"
        filename = "bibliography.csv"
    else:
        raise HTTPException(status_code=400, detail="Unsupported format")
    return Response(content=content, media_type=media_type,
                    headers={"Content-Disposition": f"attachment; filename={filename}"})
