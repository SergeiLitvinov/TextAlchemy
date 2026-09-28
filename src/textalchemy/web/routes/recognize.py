"""API OCR-распознавания."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from fastapi import File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from textalchemy.recognize import OcrEngine
from textalchemy.web.app import app
from textalchemy.web.services.ocr_drafts import (
    MAX_TEXT_LENGTH,
    DraftConflictError,
    create_draft,
    draft_store,
    export_draft,
    get_draft,
    save_draft,
)
from textalchemy.web.tasks import TaskStore
from textalchemy.web.workspace import create_web_workspace, save_upload

_SCENARIOS = ("fast", "structure", "scan")


class OcrTextEdit(BaseModel):
    text: str = Field(max_length=MAX_TEXT_LENGTH)
    revision: int = Field(ge=1)


def _store() -> TaskStore:
    from textalchemy.web.app import tasks_store

    return draft_store(tasks_store)


def _remember(payload: dict, source_name: str) -> dict:
    return {**payload, **create_draft(_store(), text=payload["text"], source_name=source_name)}


@contextmanager
def _draft_errors() -> Iterator[None]:
    try:
        yield
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except DraftConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ValueError, ImportError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=503, detail="Не удалось обратиться к хранилищу. Повторите попытку.") from error


@app.get("/api/recognize/drafts/{draft_id}")
def api_ocr_draft(draft_id: str):
    with _draft_errors():
        return get_draft(_store(), draft_id)


@app.put("/api/recognize/drafts/{draft_id}")
def api_save_ocr_draft(draft_id: str, edit: OcrTextEdit):
    with _draft_errors():
        return save_draft(_store(), draft_id, text=edit.text, revision=edit.revision)


@app.get("/api/recognize/drafts/{draft_id}/export")
def api_export_ocr_draft(draft_id: str, revision: int = Query(..., ge=1), format: str = "txt"):
    types = {"txt": "text/plain", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "pdf": "application/pdf", "model": "application/json"}
    with _draft_errors():
        content = export_draft(_store(), draft_id, revision=revision, format=format)
    filename = "corrected.model.json" if format == "model" else f"corrected.{format}"
    return Response(content, media_type=types[format], headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Document-Revision": str(revision),
        "Cache-Control": "no-store",
    })


@app.post("/api/recognize")
async def api_recognize(
    file: UploadFile = File(...),
    lang: str = Form("rus+eng"),
    gpu: bool = Form(False),
    mode: str = Form("printed"),
    scenario: str = Form("structure"),
):
    fname = file.filename or "document.pdf"
    workspace = create_web_workspace()
    try:
        tmp = await save_upload(workspace, file, fallback=fname)
        engine = OcrEngine(languages=lang.split("+"), use_gpu=gpu)
        handwriting = mode == "handwriting"

        if tmp.suffix.lower() == ".pdf":
            if scenario not in _SCENARIOS:
                return {"success": False, "error": f"unknown scenario: {scenario}"}
            if scenario == "scan" and not engine.is_available:
                return {"success": False, "error": "OCR-движок недоступен. Установите OCR или выберите обычный PDF с текстом."}
            from textalchemy.formats.pdf_ocr_merge import read_pdf_scenario

            result = read_pdf_scenario(
                str(tmp),
                mode=scenario,
                ocr_engine=engine,
                handwriting=handwriting,
            )
            return _remember({"success": True, "text": result.plain, "pages": result.pages,
                    "backend": engine.backend_name if "+ocr" in result.engine else "text_layer",
                    "scenario": scenario}, fname)

        if not engine.is_available:
            return {"success": False, "error": "OCR-движок недоступен. Установите OCR для распознавания изображения."}
        result = engine.recognize(tmp, handwriting=handwriting)
        return _remember({"success": True, "text": result.text, "confidence": result.confidence,
                "backend": engine.backend_name}, fname)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    finally:
        workspace.cleanup()
