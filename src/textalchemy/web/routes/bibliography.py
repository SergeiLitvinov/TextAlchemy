"""API управления библиотекой (CRUD bibliography + smart-parse + operations)."""
from __future__ import annotations

import inspect
import json
from typing import Any

from fastapi import File, Form, HTTPException, UploadFile

from textalchemy.core.registry import all_operations
from textalchemy.organize import BibliographyParser as PipelineBibliographyParser
from textalchemy.pipeline import register_builtin_operations
from textalchemy.pipeline.bibliography import smart_parse_bibliography
from textalchemy.web.app import _load_bib, _save_bib, app
from textalchemy.web.workspace import create_web_workspace, save_upload


@app.get("/api/info")
async def api_info():
    return {
        "name": "TextAlchemy",
        "version": app.version,
        "modules": ["extract", "convert", "organize", "generate", "recognize"],
    }


@app.get("/api/bibliography")
async def api_get_bibliography():
    return _load_bib()


@app.post("/api/bibliography")
async def api_add_bib_item(
    authors: str = Form(...),
    title: str = Form(...),
    doc_type: str = Form("article"),
    year: str = Form(""),
    journal: str = Form(""),
    publisher: str = Form(""),
    city: str = Form(""),
    pages: str = Form(""),
    isbn: str = Form(""),
    doi: str = Form(""),
    source: str = Form(""),
):
    items = _load_bib()
    item: dict = {
        "id": None,
        "authors": [a.strip() for a in authors.split(";") if a.strip()],
        "title": title,
        "doc_type": doc_type,
        "year": year,
        "journal": journal,
        "publisher": publisher,
        "city": city,
        "pages": pages,
        "isbn": isbn,
        "doi": doi,
        "source": source,
    }
    items.append(item)
    _save_bib(items)
    return {"success": True, "item": item}


@app.put("/api/bibliography/{item_id}")
async def api_update_bib_item(
    item_id: int,
    authors: str = Form(...),
    title: str = Form(...),
    doc_type: str = Form("article"),
    year: str = Form(""),
    journal: str = Form(""),
    publisher: str = Form(""),
    city: str = Form(""),
    pages: str = Form(""),
    isbn: str = Form(""),
    doi: str = Form(""),
    source: str = Form(""),
):
    items = _load_bib()
    for item in items:
        if item.get("id") == item_id:
            item.update({
                "authors": [a.strip() for a in authors.split(";") if a.strip()],
                "title": title,
                "doc_type": doc_type,
                "year": year,
                "journal": journal,
                "publisher": publisher,
                "city": city,
                "pages": pages,
                "isbn": isbn,
                "doi": doi,
                "source": source,
            })
            _save_bib(items)
            return {"success": True, "item": item}
    raise HTTPException(status_code=404, detail="Item not found")


@app.delete("/api/bibliography/{item_id}")
async def api_delete_bib_item(item_id: int):
    items = _load_bib()
    items = [i for i in items if i.get("id") != item_id]
    _save_bib(items)
    return {"success": True}


@app.post("/api/bibliography/import")
async def api_import_bib(file: UploadFile = File(...)):
    fname = file.filename or "import.json"
    workspace = create_web_workspace()
    try:
        tmp_file = await save_upload(workspace, file, fallback=fname)
        items = PipelineBibliographyParser.parse_file(str(tmp_file))
        data = PipelineBibliographyParser.to_json(items)
        existing = _load_bib()
        next_id = max((i.get("id", 0) for i in existing), default=0) + 1
        for i, item in enumerate(data):
            item["id"] = next_id + i
            existing.append(item)
        _save_bib(existing)
        return {"success": True, "count": len(data)}
    finally:
        workspace.cleanup()


@app.post("/api/bibliography/smart-parse")
async def api_smart_parse(text: str = Form(...)):
    items = smart_parse_bibliography(text=text)
    return {"success": True, "items": [
        {"index": i.index, "authors": i.authors, "title": i.title, "year": i.year}
        for i in items
    ]}


@app.get("/api/operations")
async def api_operations():
    register_builtin_operations()
    result = []
    for op in all_operations():
        params: dict[str, Any] = {}
        try:
            signature = inspect.signature(op.func)
        except (TypeError, ValueError):  # pragma: no cover
            signature = None
        if signature is not None:
            for name, param in signature.parameters.items():
                if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                    continue
                params[name] = {
                    "default": _param_default(param.default),
                    "required": param.default is inspect.Parameter.empty,
                    "annotation": _annotation_name(param.annotation),
                }
        result.append({
            "id": op.id,
            "input_type": op.input_type,
            "output_type": op.output_type,
            "input_param": op.input_param,
            "description": op.description,
            "tags": op.tags,
            "params": params,
        })
    return result


def _param_default(value: Any) -> Any:
    """Превратить значение по умолчанию в JSON-safe (коллекции — как JSON-строка)."""
    if value is inspect.Parameter.empty or value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=False)
    except (TypeError, ValueError):
        return repr(value)


def _annotation_name(annotation: Any) -> str:
    """Упростить аннотацию параметра до строки (Optional[X] -> X)."""
    if annotation is inspect.Parameter.empty:
        return ""
    origin = getattr(annotation, "__origin__", None)
    if origin is not None:
        args = getattr(annotation, "__args__", ())
        if origin is bool:
            return "bool"
        if origin in (list, tuple, set, dict):
            name = getattr(origin, "__name__", str(origin))
            if args:
                inner = ", ".join(_annotation_name(a) for a in args)
                return f"{name}[{inner}]"
            return name
        if origin is None and args:
            return ", ".join(_annotation_name(a) for a in args)
        return getattr(origin, "__name__", str(origin))
    return getattr(annotation, "__name__", str(annotation))
