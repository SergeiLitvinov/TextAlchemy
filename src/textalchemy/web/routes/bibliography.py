"""API управления библиотекой (CRUD bibliography + smart-parse + operations)."""

from __future__ import annotations

from fastapi import File, Form, HTTPException, UploadFile

from textalchemy.web.app import _bibliography_service, app
from textalchemy.web.services.bibliography import BibliographyInput
from textalchemy.web.services.operation_catalog import operation_catalog
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
    return _bibliography_service().list_items()


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
    return _bibliography_service().add(
        BibliographyInput(
            authors=authors,
            title=title,
            doc_type=doc_type,
            year=year,
            journal=journal,
            publisher=publisher,
            city=city,
            pages=pages,
            isbn=isbn,
            doi=doi,
            source=source,
        )
    )


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
    try:
        return _bibliography_service().update(
            item_id,
            BibliographyInput(
                authors=authors,
                title=title,
                doc_type=doc_type,
                year=year,
                journal=journal,
                publisher=publisher,
                city=city,
                pages=pages,
                isbn=isbn,
                doi=doi,
                source=source,
            ),
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.delete("/api/bibliography/{item_id}")
async def api_delete_bib_item(item_id: int):
    return _bibliography_service().delete(item_id)


@app.post("/api/bibliography/import")
async def api_import_bib(file: UploadFile = File(...)):
    fname = file.filename or "import.json"
    workspace = create_web_workspace()
    try:
        tmp_file = await save_upload(workspace, file, fallback=fname)
        return _bibliography_service().import_file(tmp_file)
    finally:
        workspace.cleanup()


@app.post("/api/bibliography/smart-parse")
async def api_smart_parse(text: str = Form(...)):
    return _bibliography_service().smart_parse(text)


@app.get("/api/operations")
async def api_operations():
    return operation_catalog()
