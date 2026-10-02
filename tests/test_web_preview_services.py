"""Прямые проверки предпросмотра, смены результата и очистки инспекции."""

from __future__ import annotations

import asyncio
import importlib
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import fitz
import pytest

from tests.test_web_ingest_services import BytesUpload
from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.web.services.conversion_inspection import ConversionInspectionService
from textalchemy.web.services.conversion_preview import ConversionPreviewService, PreviewError
from textalchemy.web.tasks import TaskStore


def pdf(path: Path, text: str, pages: int = 2) -> None:
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page(width=180, height=240)
            page.insert_text((15, 30), f"{text} {index + 1}")
        document.save(path)


@pytest.fixture
def preview_service(tmp_path: Path) -> ConversionPreviewService:
    store = TaskStore(tmp_path / "tasks")
    source, target = tmp_path / "source.pdf", tmp_path / "target.pdf"
    pdf(source, "Source")
    pdf(target, "Changed")
    store.store_source("example", source, source.name)
    artifact = store.store_artifact("example", target, target.name)
    store.set("example", {"status": "done", "artifact": artifact})
    return ConversionPreviewService(store)


def test_real_pdf_meta_pages_diff_and_server_cache(preview_service: ConversionPreviewService) -> None:
    service = preview_service
    meta = service.meta("example")
    assert meta == {side: {"available": True, "pages": 2, "error": None} for side in ("source", "target")}
    original = service.page("example", page=2, dpi=72).content
    changed = service.page("example", side="target", page=2, dpi=72).content
    assert original.startswith(b"\x89PNG") and changed.startswith(b"\x89PNG") and original != changed
    assert service.page("example", page=2, dpi=72).content == original
    image = service.diff("example", page=2, dpi=72)
    assert image.content.startswith(b"\x89PNG") and 0 <= image.similarity < 1 and image.rmse > 0
    assert list((service.store.root / "example/preview").glob("*/source-1-72dpi.png"))
    with pytest.raises(PreviewError) as error:
        service.page("example", page=3)
    assert error.value.status_code == 404


@pytest.mark.parametrize("state", ["queued", "running", "error", "cancelled"])
def test_unfinished_task_does_not_create_cache(preview_service: ConversionPreviewService, state: str) -> None:
    store = preview_service.store
    store.set("example", {**store.get("example"), "status": state})
    with pytest.raises(PreviewError) as error:
        preview_service.meta("example")
    assert error.value.status_code == 409
    assert not (store.root / "example/preview").exists()


@pytest.mark.parametrize("action", ["meta", "page", "diff"])
def test_expiry_during_render_does_not_recreate_or_serve_task_cache(
    preview_service: ConversionPreviewService, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    store = preview_service.store
    now = store.get("example")["_ts"]
    module = importlib.import_module("textalchemy.web.tasks")
    monkeypatch.setattr(module.time, "time", lambda: now)

    def expire(cache: Path, *_args: Any, **_kwargs: Any) -> Any:
        nonlocal now
        now += store.ttl_seconds + 1
        assert store.get("example") is None
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "late.png").write_bytes(b"late stale image")
        return 2 if action == "meta" else b"stale image"

    service = replace(preview_service, counter=expire if action == "meta" else preview_service.counter, renderer=expire)
    with pytest.raises(PreviewError) as error:
        getattr(service, action)("example")
    assert error.value.status_code == 404
    assert not (store.root / "example").exists()


def test_replaced_result_rejects_old_request_and_preserves_new_cache(preview_service: ConversionPreviewService) -> None:
    store = preview_service.store
    new_cache: Path | None = None

    def replace_result(cache: Path, *_args: Any, **_kwargs: Any) -> bytes:
        nonlocal new_cache
        store.clear_result("example")
        store.set("example", {"status": "done", "artifact": "new.pdf", "revision": 2})
        new_cache = store.preview_revision_dir("example", expected=store.get("example"))
        (new_cache / "new.png").write_bytes(b"new image")
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "late.png").write_bytes(b"old image")
        return b"old image"

    service = replace(preview_service, renderer=replace_result)
    with pytest.raises(PreviewError) as error:
        service.page("example")
    assert error.value.status_code == 409
    assert store.get("example")["revision"] == 2
    assert (new_cache / "new.png").read_bytes() == b"new image"
    assert list((store.root / "example/preview").iterdir()) == [new_cache]


def test_counter_failure_remains_side_metadata_and_renderer_failure_is_readable(
    preview_service: ConversionPreviewService,
) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("renderer unavailable")

    service = replace(preview_service, counter=fail)
    assert service.meta("example")["source"] == {"available": False, "pages": 0, "error": "renderer unavailable"}
    with pytest.raises(PreviewError) as error:
        replace(preview_service, renderer=fail).page("example")
    assert error.value.status_code == 404 and "отрисовать" in str(error.value)


def test_real_docx_inspection_public_name_and_cleanup(tmp_path: Path) -> None:
    from docx import Document

    document = Document()
    document.add_paragraph("Inspect me")
    path = tmp_path / "fixture.docx"
    document.save(path)
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    service = ConversionInspectionService(workspace_factory=lambda: ArtifactWorkspace(parent=workspace_root))
    result = asyncio.run(service.inspect(BytesUpload("Документ.docx", path.read_bytes())))
    assert result["success"] and result["inspection"]["source_path"] == "Документ.docx"
    assert result["inspection"]["metrics"]["paragraphs"] >= 1
    assert list(workspace_root.iterdir()) == []


def test_inspection_error_cleans_partial_upload_and_worker_files(tmp_path: Path) -> None:
    def fail(path: Path) -> None:
        assert path.is_file()
        raise OSError("inspection failed")

    service = ConversionInspectionService(workspace_factory=lambda: ArtifactWorkspace(parent=tmp_path), inspector=fail)
    with pytest.raises(OSError, match="inspection failed"):
        asyncio.run(service.inspect(BytesUpload("example.txt", b"some text")))
    assert list(tmp_path.iterdir()) == []


def test_cancelled_inspection_keeps_file_until_worker_finishes(tmp_path: Path) -> None:
    entered, release = threading.Event(), threading.Event()
    read_after_cancel = []

    def inspect(path: Path) -> None:
        entered.set()
        assert release.wait(timeout=10)
        read_after_cancel.append(path.read_bytes())

    service = ConversionInspectionService(workspace_factory=lambda: ArtifactWorkspace(parent=tmp_path), inspector=inspect)

    async def run() -> None:
        pending = asyncio.create_task(service.inspect(BytesUpload("example.txt", b"source")))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            pending.cancel()
            await asyncio.sleep(0)
            assert list(tmp_path.glob("*/example.txt"))
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending

    asyncio.run(run())
    assert read_after_cancel == [b"source"] and list(tmp_path.iterdir()) == []
