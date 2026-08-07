"""API OCR-распознавания."""
from __future__ import annotations

from fastapi import File, Form, UploadFile

from textalchemy.recognize import OcrEngine
from textalchemy.web.app import app
from textalchemy.web.workspace import create_web_workspace, save_upload

_SCENARIOS = ("fast", "structure", "scan")


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
                return {"success": True, "text": f"[STUB] OCR for: {file.filename}",
                        "confidence": 0.0, "backend": None, "scenario": scenario}
            from textalchemy.formats.pdf_ocr_merge import read_pdf_scenario

            result = read_pdf_scenario(
                str(tmp),
                mode=scenario,
                ocr_engine=engine,
                handwriting=handwriting,
            )
            return {"success": True, "text": result.plain, "pages": result.pages,
                    "backend": engine.backend_name if "+ocr" in result.engine else "text_layer",
                    "scenario": scenario}

        if not engine.is_available:
            return {"success": True, "text": f"[STUB] OCR for: {file.filename}",
                    "confidence": 0.0, "backend": None}
        result = engine.recognize(tmp, handwriting=handwriting)
        return {"success": True, "text": result.text, "confidence": result.confidence,
                "backend": engine.backend_name}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    finally:
        workspace.cleanup()
