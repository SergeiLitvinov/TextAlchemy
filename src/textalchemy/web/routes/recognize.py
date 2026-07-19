"""API OCR-распознавания."""
from __future__ import annotations

import os
import tempfile

from fastapi import File, UploadFile

from textalchemy.recognize import OcrEngine
from textalchemy.web.app import app


@app.post("/api/recognize")
async def api_recognize(file: UploadFile = File(...)):
    from pathlib import Path

    fname = file.filename or "document.pdf"
    tmp = Path(tempfile.mkdtemp()) / fname
    tmp.write_bytes(await file.read())
    try:
        engine = OcrEngine()
        if engine.is_available:
            result = engine.recognize(tmp)
            return {"success": True, "text": result.text, "confidence": result.confidence,
                    "backend": engine.backend_name}
        return {"success": True, "text": f"[STUB] OCR for: {file.filename}",
                "confidence": 0.0, "backend": None}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    finally:
        os.unlink(tmp)
