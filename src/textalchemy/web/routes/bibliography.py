"""API управления библиотекой (CRUD bibliography + smart-parse + operations)."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import File, Form, HTTPException, UploadFile

from textalchemy.core.registry import all_operations
from textalchemy.organize import BibliographyParser as PipelineBibliographyParser
from textalchemy.pipeline.bibliography import smart_parse_bibliography
from textalchemy.web.app import _load_bib, _save_bib, app


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
    workdir = Path(tempfile.mkdtemp(prefix="textalchemy_web_"))
    tmp_file = workdir / fname
    tmp_file.write_bytes(await file.read())
    try:
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
        shutil.rmtree(workdir, ignore_errors=True)


@app.post("/api/bibliography/smart-parse")
async def api_smart_parse(text: str = Form(...)):
    items = smart_parse_bibliography(text=text)
    return {"success": True, "items": [
        {"index": i.index, "authors": i.authors, "title": i.title, "year": i.year}
        for i in items
    ]}


@app.get("/api/operations")
async def api_operations():
    return [{"id": op.id, "input_type": op.input_type, "output_type": op.output_type,
             "input_param": op.input_param, "description": op.description, "tags": op.tags}
            for op in all_operations()]
