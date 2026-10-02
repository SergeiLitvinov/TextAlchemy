"""HTTP-адаптер извлечения текста/LaTeX из загруженных файлов."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import File, Form, UploadFile
from fastapi.responses import Response

from textalchemy.web.app import app
from textalchemy.web.services.extraction import ExtractedDownload, ExtractionService
from textalchemy.web.services.extraction import docx_to_latex as docx_to_latex
from textalchemy.web.services.extraction import extract_text as extract_text
from textalchemy.web.services.extraction import ingest_file as ingest_file
from textalchemy.web.workspace import create_web_workspace, save_upload


def _service() -> ExtractionService:
    return ExtractionService(
        workspace_factory=create_web_workspace,
        saver=save_upload,
        ingest=ingest_file,
        read_text=extract_text,
        latex_writer=docx_to_latex,
    )


@app.post("/api/extract/text")
async def api_extract_text(file: UploadFile = File(...), fmt: str = Form("auto")) -> dict[str, Any]:
    return await _service().text(file)


@app.post("/api/extract/latex", response_model=None)
async def api_extract_latex(
    file: UploadFile = File(...),
    doc_type: str = Form("manuscript"),
) -> Response | dict[str, Any]:
    result = await _service().latex(file, doc_type=doc_type)
    if isinstance(result, ExtractedDownload):
        return Response(
            result.content,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=extracted.tex; filename*=UTF-8''{quote(result.filename, safe='')}",
            },
        )
    return result
