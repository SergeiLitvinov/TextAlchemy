"""PDF reading-order editor endpoints."""
from contextlib import contextmanager

from fastapi import File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, StrictInt
from starlette.concurrency import run_in_threadpool

from textalchemy.web.app import app, templates
from textalchemy.web.services import pdf_order
from textalchemy.web.services.ocr_drafts import DraftConflictError
from textalchemy.web.workspace import create_web_workspace, save_upload


class OrderEdit(BaseModel):
    revision: int = Field(ge=1)
    order: list[list[str]]
    classifications: dict[str, str] = Field(default_factory=dict)
    table_ranges: dict[str, list[StrictInt]] = Field(default_factory=dict)


def _store():
    from textalchemy.web.app import tasks_store

    return pdf_order.store_for(tasks_store)


@contextmanager
def _errors():
    try:
        yield
    except DraftConflictError as error:
        raise HTTPException(409, str(error)) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except (ValueError, ImportError) as error:
        raise HTTPException(422, str(error)) from error
    except OSError as error:
        raise HTTPException(503, "Хранилище недоступно. Повторите попытку.") from error


@app.get("/pdf-order")
def pdf_order_page(request: Request):
    return templates.TemplateResponse(request, "pdf_order.html")


@app.post("/api/pdf-order")
async def import_pdf(file: UploadFile = File(...)):
    with _errors(), create_web_workspace() as workspace:
        path = await save_upload(workspace, file, fallback="document.pdf")
        return await run_in_threadpool(pdf_order.create, _store(), path, file.filename or "document.pdf")


@app.get("/api/pdf-order/{draft_id}")
def get_order(draft_id: str):
    with _errors():
        return pdf_order.summary(pdf_order.load(_store(), draft_id))


@app.put("/api/pdf-order/{draft_id}")
def save_order(draft_id: str, edit: OrderEdit):
    with _errors():
        return pdf_order.reorder(_store(), draft_id, edit.revision, edit.order, edit.classifications, edit.table_ranges)


@app.get("/api/pdf-order/{draft_id}/pages/{page}")
def get_page(draft_id: str, page: int):
    with _errors():
        return Response(pdf_order.page_image(_store(), draft_id, page), media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/pdf-order/{draft_id}/export")
def export_order(draft_id: str, revision: int = Query(..., ge=1), format: str = "model"):
    with _errors():
        content = pdf_order.export(_store(), draft_id, revision, format)
    filename = "ordered.model.json" if format == "model" else "ordered.docx"
    media = "application/json" if format == "model" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"',
                    "Cache-Control": "no-store", "X-Document-Revision": str(revision)})


@app.get("/api/pdf-order/{draft_id}/diagnostics")
def get_diagnostics(draft_id: str, revision: int = Query(..., ge=1)):
    with _errors():
        return JSONResponse(pdf_order.diagnostics(_store(), draft_id, revision), headers={"Cache-Control": "no-store"})
