"""API OCR-распознавания."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from textalchemy.web.app import app
from textalchemy.web.services.ocr_drafts import (
    MAX_TEXT_LENGTH,
    DraftConflictError,
    draft_store,
    export_draft,
    get_draft,
    save_draft,
)
from textalchemy.web.services.recognition import OcrEngine as OcrEngine
from textalchemy.web.services.recognition import RecognitionService
from textalchemy.web.tasks import TaskStore
from textalchemy.web.workspace import create_web_workspace, save_upload


class OcrTextEdit(BaseModel):
    text: str = Field(max_length=MAX_TEXT_LENGTH)
    revision: int = Field(ge=1)


def _store() -> TaskStore:
    from textalchemy.web.app import tasks_store

    return draft_store(tasks_store)


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
def api_ocr_draft(draft_id: str) -> dict[str, Any]:
    with _draft_errors():
        return get_draft(_store(), draft_id)


@app.put("/api/recognize/drafts/{draft_id}")
def api_save_ocr_draft(draft_id: str, edit: OcrTextEdit) -> dict[str, Any]:
    with _draft_errors():
        return save_draft(_store(), draft_id, text=edit.text, revision=edit.revision)


@app.get("/api/recognize/drafts/{draft_id}/export")
def api_export_ocr_draft(draft_id: str, revision: int = Query(..., ge=1), format: str = "txt") -> Response:
    types = {
        "txt": "text/plain",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "model": "application/json",
    }
    with _draft_errors():
        content = export_draft(_store(), draft_id, revision=revision, format=format)
    filename = "corrected.model.json" if format == "model" else f"corrected.{format}"
    return Response(
        content,
        media_type=types[format],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Document-Revision": str(revision),
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/recognize")
async def api_recognize(
    file: UploadFile = File(...),
    lang: str = Form("rus+eng"),
    gpu: bool = Form(False),
    mode: str = Form("printed"),
    scenario: str = Form("structure"),
) -> dict[str, Any]:
    service = RecognitionService(
        draft_store_factory=_store, engine_factory=OcrEngine, workspace_factory=create_web_workspace, saver=save_upload
    )
    return await service.recognize(file, lang=lang, gpu=gpu, mode=mode, scenario=scenario)
