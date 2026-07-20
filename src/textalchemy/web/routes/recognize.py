"""API OCR-распознавания."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import File, Form, UploadFile

from textalchemy.recognize import OcrEngine
from textalchemy.web.app import app


@app.post("/api/recognize")
async def api_recognize(
    file: UploadFile = File(...),
    lang: str = Form("rus+eng"),
    gpu: bool = Form(False),
    mode: str = Form("printed"),
):
    fname = file.filename or "document.pdf"
    workdir = Path(tempfile.mkdtemp(prefix="textalchemy_web_"))
    tmp = workdir / fname
    tmp.write_bytes(await file.read())
    try:
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
        shutil.rmtree(workdir, ignore_errors=True)
