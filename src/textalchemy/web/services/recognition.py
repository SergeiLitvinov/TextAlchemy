"""Распознавание PDF/изображения и сохранение исправляемого текста вне HTTP-слоя."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.recognize import OcrEngine
from textalchemy.web.services.ocr_drafts import create_draft
from textalchemy.web.services.upload_input import UploadSaver, UploadSource, save_input, staged_upload
from textalchemy.web.tasks import TaskStore


@dataclass
class RecognitionService:
    """Движок, загрузка и хранилище подменяются; неудачный запуск не создаёт черновика."""

    draft_store_factory: Callable[[], TaskStore]
    engine_factory: Callable[..., OcrEngine] = OcrEngine
    workspace_factory: Callable[[], ArtifactWorkspace] = ArtifactWorkspace
    saver: UploadSaver = save_input

    def _remember(self, payload: dict[str, Any], source_name: str) -> dict[str, Any]:
        draft = create_draft(self.draft_store_factory(), text=payload["text"], source_name=source_name)
        return {**payload, **draft}

    async def recognize(
        self,
        upload: UploadSource,
        *,
        lang: str = "rus+eng",
        gpu: bool = False,
        mode: str = "printed",
        scenario: str = "structure",
    ) -> dict[str, Any]:
        try:
            async with staged_upload(
                upload, fallback="document.pdf", workspace_factory=self.workspace_factory, saver=self.saver
            ) as (_, source):
                payload = self._read(source, lang=lang, gpu=gpu, mode=mode, scenario=scenario)
                if not payload["success"]:
                    return payload
                return self._remember(payload, upload.filename or "document.pdf")
        except Exception as error:  # noqa: BLE001
            return {"success": False, "error": str(error)}

    def _read(self, source: Path, *, lang: str, gpu: bool, mode: str, scenario: str) -> dict[str, Any]:
        engine = self.engine_factory(languages=lang.split("+"), use_gpu=gpu)
        handwriting = mode == "handwriting"
        if source.suffix.lower() == ".pdf":
            if scenario not in ("fast", "structure", "scan"):
                return {"success": False, "error": f"unknown scenario: {scenario}"}
            if scenario == "scan" and not engine.is_available:
                return {"success": False, "error": "OCR-движок недоступен. Установите OCR или выберите обычный PDF с текстом."}
            from textalchemy.formats.pdf_ocr_merge import read_pdf_scenario

            result = read_pdf_scenario(str(source), mode=scenario, ocr_engine=engine, handwriting=handwriting)
            return {
                "success": True,
                "text": result.plain,
                "pages": result.pages,
                "backend": engine.backend_name if "+ocr" in result.engine else "text_layer",
                "scenario": scenario,
            }
        if not engine.is_available:
            return {"success": False, "error": "OCR-движок недоступен. Установите OCR для распознавания изображения."}
        result = engine.recognize(source, handwriting=handwriting)
        return {"success": True, "text": result.text, "confidence": result.confidence, "backend": engine.backend_name}
