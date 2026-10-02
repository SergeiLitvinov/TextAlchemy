"""Сервисы извлечения и OCR сохраняют данные и освобождают временные файлы без HTTP-клиента."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.web.services.extraction import ExtractedDownload, ExtractionService
from textalchemy.web.services.ocr_drafts import get_draft
from textalchemy.web.services.recognition import RecognitionService
from textalchemy.web.tasks import TaskStore


@dataclass
class BytesUpload:
    filename: str | None
    content: bytes
    offset: int = 0

    async def read(self, size: int = -1) -> bytes:
        end = len(self.content) if size < 0 else min(len(self.content), self.offset + size)
        data = self.content[self.offset : end]
        self.offset = end
        return data


def test_text_extraction_returns_real_text_and_cleans_input(tmp_path: Path) -> None:
    upload = BytesUpload("Заметки.txt", "Текст из файла".encode())
    service = ExtractionService(workspace_factory=lambda: ArtifactWorkspace(parent=tmp_path))
    result = asyncio.run(service.text(upload))
    assert result == {"success": True, "text": "Текст из файла", "filename": "Заметки.txt"}
    assert not list(tmp_path.iterdir())


def test_latex_result_survives_cleanup(tmp_path: Path) -> None:
    def write(source: Path, output: Path, doc_type: str) -> None:
        assert source.read_bytes() == b"docx" and doc_type == "manuscript"
        output.write_text("\\section{Раздел}", encoding="utf-8")

    service = ExtractionService(workspace_factory=lambda: ArtifactWorkspace(parent=tmp_path), latex_writer=write)
    result = asyncio.run(service.latex(BytesUpload("Работа.docx", b"docx")))
    assert isinstance(result, ExtractedDownload) and result.filename == "Работа.tex"
    assert "Раздел" in result.content and not list(tmp_path.iterdir())


@pytest.mark.parametrize("kind", ["text", "latex"])
def test_upload_failure_cleans_partial_input(tmp_path: Path, kind: str) -> None:
    class BrokenUpload(BytesUpload):
        async def read(self, size: int = -1) -> bytes:
            if self.offset:
                raise OSError("read failed")
            return await super().read(size)

    service = ExtractionService(workspace_factory=lambda: ArtifactWorkspace(parent=tmp_path))
    result = asyncio.run(getattr(service, kind)(BrokenUpload("input.txt", b"partial")))
    assert result["success"] is False and result["error"] == "read failed"
    assert not list(tmp_path.iterdir())


def test_failed_export_removes_partial_output(tmp_path: Path) -> None:
    def fail(source: Path, output: Path, doc_type: str) -> None:
        output.write_bytes(b"partial")
        raise RuntimeError("writer failed")

    service = ExtractionService(workspace_factory=lambda: ArtifactWorkspace(parent=tmp_path), latex_writer=fail)
    result = asyncio.run(service.latex(BytesUpload("input.docx", b"docx")))
    assert result["success"] is False and not list(tmp_path.iterdir())


def test_ocr_receives_settings_and_persists_editable_text(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    store = TaskStore(tmp_path / "drafts")
    options: dict[str, Any] = {}

    def recognize(source: Path, *, handwriting: bool) -> SimpleNamespace:
        assert source.read_bytes() == b"image"
        options["handwriting"] = handwriting
        return SimpleNamespace(text="Распознано\n", confidence=0.9)

    def engine(**settings: Any) -> SimpleNamespace:
        options.update(settings)
        return SimpleNamespace(is_available=True, backend_name="fixture", recognize=recognize)

    service = RecognitionService(lambda: store, engine_factory=engine, workspace_factory=lambda: ArtifactWorkspace(parent=work))
    result = asyncio.run(service.recognize(BytesUpload("Скан.png", b"image"), lang="rus+eng", gpu=True, mode="handwriting"))
    assert result["success"] and result["revision"] == 1 and result["confidence"] == 0.9
    assert options == {"languages": ["rus", "eng"], "use_gpu": True, "handwriting": True}
    restored = get_draft(TaskStore(store.root), result["draft_id"])
    assert restored["text"] == "Распознано\n" and restored["source_name"] == "Скан.png"
    assert not list(work.iterdir())


@pytest.mark.parametrize("filename,scenario", [("image.png", "scan"), ("scan.pdf", "scan"), ("scan.pdf", "unknown")])
def test_unavailable_ocr_or_bad_scenario_never_creates_draft(tmp_path: Path, filename: str, scenario: str) -> None:
    def store() -> TaskStore:
        raise AssertionError("Неудачный запуск не создаёт черновик")

    engine = SimpleNamespace(is_available=False, backend_name=None)
    service = RecognitionService(
        store, engine_factory=lambda **kwargs: engine, workspace_factory=lambda: ArtifactWorkspace(parent=tmp_path)
    )
    result = asyncio.run(service.recognize(BytesUpload(filename, b"input"), scenario=scenario))
    assert result["success"] is False and not list(tmp_path.iterdir())


def test_pdf_text_layer_works_without_ocr_and_cleans_input(tmp_path: Path) -> None:
    import fitz

    document = fitz.open()
    document.new_page().insert_text((50, 50), "Existing text layer")
    content = document.tobytes()
    document.close()
    work = tmp_path / "work"
    work.mkdir()
    service = RecognitionService(
        lambda: TaskStore(tmp_path / "drafts"),
        engine_factory=lambda **kwargs: SimpleNamespace(is_available=False, backend_name=None),
        workspace_factory=lambda: ArtifactWorkspace(parent=work),
    )
    result = asyncio.run(service.recognize(BytesUpload("source.pdf", content), scenario="fast"))
    assert result["success"] and result["backend"] == "text_layer" and result["pages"] == 1
    assert "Existing text layer" in result["text"] and result["draft_id"]
    assert not list(work.iterdir())


def test_ocr_storage_failure_cleans_source(tmp_path: Path) -> None:
    def store() -> TaskStore:
        raise OSError("store unavailable")

    engine = SimpleNamespace(
        is_available=True, backend_name="fixture", recognize=lambda *args, **kwargs: SimpleNamespace(text="Read", confidence=0.9)
    )
    service = RecognitionService(
        store, engine_factory=lambda **kwargs: engine, workspace_factory=lambda: ArtifactWorkspace(parent=tmp_path)
    )
    result = asyncio.run(service.recognize(BytesUpload("image.png", b"image")))
    assert result["error"] == "store unavailable" and not list(tmp_path.iterdir())


def test_upload_quota_failure_cleans_source_before_ocr(tmp_path: Path) -> None:
    def store() -> TaskStore:
        raise AssertionError("Черновик не создаётся при превышении квоты")

    service = RecognitionService(store, workspace_factory=lambda: ArtifactWorkspace(parent=tmp_path, max_bytes=2))
    result = asyncio.run(service.recognize(BytesUpload("image.png", b"oversized")))
    assert result["success"] is False and "quota" in result["error"]
    assert not list(tmp_path.iterdir())
