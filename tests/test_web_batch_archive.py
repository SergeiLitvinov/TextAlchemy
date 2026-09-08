"""ZIP пакета: готовые результаты, частичные ошибки, TTL и границы выдачи."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from textalchemy.web.app import app
from textalchemy.web.routes import convert as facade
from textalchemy.web.services.batch_archive import build_batch_archive
from textalchemy.web.tasks import TaskStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TaskStore:
    storage = TaskStore(tmp_path / "tasks")
    monkeypatch.setattr(facade, "tasks_store", storage)
    source = tmp_path / "output.txt"
    for index in range(2):
        source.write_text(f"Результат {index}", encoding="utf-8")
        artifact = storage.store_artifact(f"task{index}", source, "same.txt")
        storage.set(f"task{index}", {"status": "done", "artifact": artifact})
    storage.set("failed", {"status": "error", "error": "Conversion failed"})
    storage.set_job(
        "batch",
        {
            "files": [
                {"task_id": "task0", "name": "same.docx"},
                {"task_id": "task1", "name": "same.docx"},
                {"task_id": "failed", "name": "bad.docx"},
                {"task_id": "expired", "name": "old.docx"},
            ]
        },
    )
    return storage


def test_archive_download_keeps_duplicates_and_reports_partial_failures(store: TaskStore) -> None:
    response = TestClient(app).get("/api/convert/jobs/batch/archive")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == ["01/same.txt", "02/same.txt", "manifest.json"]
        assert archive.read("01/same.txt").decode() == "Результат 0"
        assert archive.read("02/same.txt").decode() == "Результат 1"
        manifest = json.loads(archive.read("manifest.json"))
        assert [item["status"] for item in manifest["files"]] == ["done", "done", "error", "expired"]
        assert manifest["files"][2]["file"] is None


@pytest.mark.parametrize("status", ["queued", "running", "cancelling"])
def test_active_batch_is_not_published(store: TaskStore, status: str) -> None:
    store.set("failed", {"status": status})
    assert TestClient(app).get("/api/convert/jobs/batch/archive").status_code == 409


def test_missing_results_and_expired_job(store: TaskStore) -> None:
    store.delete("task0")
    store.set("task1", {"status": "done", "artifact": "missing.txt"})
    client = TestClient(app)
    assert client.get("/api/convert/jobs/batch/archive").status_code == 409
    store.delete_job("batch")
    assert client.get("/api/convert/jobs/batch/archive").status_code == 404


def test_quota_and_path_escape(store: TaskStore, tmp_path: Path) -> None:
    with pytest.raises(OverflowError):
        build_batch_archive(store, "batch", max_bytes=1)
    outside = tmp_path / "secret.txt"
    outside.write_text("Private", encoding="utf-8")
    store.set("task1", {"status": "done", "artifact": str(outside)})
    with build_batch_archive(store, "batch") as stream, ZipFile(stream) as archive:
        assert archive.namelist() == ["01/same.txt", "manifest.json"]
        assert json.loads(archive.read("manifest.json"))["files"][1]["status"] == "unavailable"


def test_html_result_zip_is_preserved_without_unpacking(store: TaskStore, tmp_path: Path) -> None:
    html = tmp_path / "viewer"
    html.mkdir()
    (html / "index.html").write_text("<p>Viewer</p>", encoding="utf-8")
    artifact = store.store_artifact("task0", html, "viewer")
    store.set("task0", {"status": "done", "artifact": artifact})
    with build_batch_archive(store, "batch") as stream, ZipFile(stream) as archive:
        with ZipFile(BytesIO(archive.read("01/viewer.zip"))) as viewer:
            assert viewer.read("index.html") == b"<p>Viewer</p>"


def test_failed_archive_closes_temporary_stream(store: TaskStore, monkeypatch: pytest.MonkeyPatch) -> None:
    from textalchemy.web.services import batch_archive

    stream = BytesIO()
    monkeypatch.setattr(batch_archive, "SpooledTemporaryFile", lambda **_: stream)
    with pytest.raises(OverflowError):
        build_batch_archive(store, "batch", max_bytes=1)
    assert stream.closed
