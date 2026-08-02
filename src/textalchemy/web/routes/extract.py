"""API извлечения текста/LaTeX из загруженных файлов."""
from __future__ import annotations

from fastapi import File, Form, UploadFile
from fastapi.responses import Response

from textalchemy.extract import docx_to_latex
from textalchemy.pipeline.extract import extract_text
from textalchemy.pipeline.ingest import ingest_file
from textalchemy.web.app import app
from textalchemy.web.workspace import create_web_workspace, save_upload


@app.post("/api/extract/text")
async def api_extract_text(file: UploadFile = File(...), fmt: str = Form("auto")):
    fname = file.filename or "extracted.txt"
    workspace = create_web_workspace()
    try:
        tmp = await save_upload(workspace, file, fallback=fname)
        doc = ingest_file(path=tmp)
        text = extract_text(doc=doc)
        return {"success": True, "text": text.plain, "filename": file.filename}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    finally:
        workspace.cleanup()


@app.post("/api/extract/latex")
async def api_extract_latex(
    file: UploadFile = File(...),
    doc_type: str = Form("manuscript"),
):
    fname = file.filename or "document.docx"
    workspace = create_web_workspace()
    try:
        tmp = await save_upload(workspace, file, fallback=fname)
        out = workspace.artifact_path(f"{tmp.stem}.tex")
        docx_to_latex(tmp, out, doc_type)
        content = out.read_text(encoding="utf-8")
        return Response(content=content, media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename={out.name}"})
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    finally:
        workspace.cleanup()
