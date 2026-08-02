"""API OCR-распознавания."""
from __future__ import annotations

from fastapi import File, Form, UploadFile

from textalchemy.recognize import OcrEngine
from textalchemy.web.app import app
from textalchemy.web.workspace import create_web_workspace, save_upload


@app.post("/api/recognize")
async def api_recognize(
    file: UploadFile = File(...),
    lang: str = Form("rus+eng"),
    gpu: bool = Form(False),
    mode: str = Form("printed"),
):
    fname = file.filename or "document.pdf"
    workspace = create_web_workspace()
    try:
        tmp = await save_upload(workspace, file, fallback=fname)
        engine = OcrEngine(languages=lang.split("+"), use_gpu=gpu)
        if engine.is_available:
            handwriting = mode == "handwriting"
            result = engine.recognize(tmp, handwriting=handwriting)
            return {"success": True, "text": result.text, "confidence": result.confidence,
                    "backend": engine.backend_name}
        return {"success": True, "text": f"[STUB] OCR for: {file.filename}",
                "confidence": 0.0, "backend": None}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    finally:
        workspace.cleanup()
