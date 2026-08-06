"""Тесты web.tasks — on-disk хранилище задач с TTL."""
from __future__ import annotations

import time
import zipfile

from textalchemy.web.tasks import TaskStore


def test_set_and_get_roundtrip(tmp_path):
    store = TaskStore(tmp_path)
    store.set("task-1", {"status": "done", "filename": "out.docx"})
    task = store.get("task-1")
    assert task is not None
    assert task["status"] == "done"
    assert task["filename"] == "out.docx"
    assert isinstance(task["_ts"], float)


def test_get_missing_returns_none(tmp_path):
    store = TaskStore(tmp_path)
    assert store.get("nope") is None


def test_get_stale_task_is_deleted(tmp_path, monkeypatch):
    store = TaskStore(tmp_path, ttl_seconds=10)
    store.set("old", {"status": "done"})
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 60)
    assert store.get("old") is None
    assert store.get("old") is None  # уже удалена, а не «протухла» повторно


def test_prune_removes_stale_and_keeps_fresh(tmp_path, monkeypatch):
    store = TaskStore(tmp_path, ttl_seconds=10)
    real_time = time.time
    store.set("stale", {"status": "done"})
    monkeypatch.setattr(time, "time", lambda: real_time() + 60)
    assert store.prune() == 1
    assert store.get("stale") is None
    # Свежие задачи (созданные после сдвига времени) остаются.
    store.set("fresh", {"status": "running"})
    assert store.prune() == 0
    assert store.get("fresh") is not None


def test_store_artifact_file(tmp_path):
    store = TaskStore(tmp_path)
    source = tmp_path / "source.docx"
    source.write_bytes(b"artifact-bytes")
    stored_name = store.store_artifact("task-1", source, "result.docx")
    assert stored_name == "result.docx"
    result = store.result_path("task-1", stored_name)
    assert result is not None
    assert result.read_bytes() == b"artifact-bytes"


def test_store_artifact_directory_becomes_zip(tmp_path):
    store = TaskStore(tmp_path)
    source_dir = tmp_path / "html"
    source_dir.mkdir()
    (source_dir / "index.html").write_text("<html>viewer</html>", encoding="utf-8")
    stored_name = store.store_artifact("task-1", source_dir, "deck-html")
    assert stored_name.endswith(".zip")
    result = store.result_path("task-1", stored_name)
    assert result is not None
    with zipfile.ZipFile(result) as zf:
        assert "index.html" in zf.namelist()


def test_result_path_rejects_traversal(tmp_path):
    store = TaskStore(tmp_path)
    assert store.result_path("task-1", "../outside.txt") is None


def test_delete_removes_meta_and_artifact(tmp_path):
    store = TaskStore(tmp_path)
    source = tmp_path / "source.bin"
    source.write_bytes(b"x")
    store.store_artifact("task-1", source, "result.bin")
    store.set("task-1", {"status": "done"})
    store.delete("task-1")
    assert store.get("task-1") is None
    assert not (tmp_path / "task-1").exists()
    assert not (tmp_path / "task-1.json").exists()


def test_meta_is_json_persisted(tmp_path):
    """Задача переживает пересоздание хранилища (перезапуск процесса)."""
    store = TaskStore(tmp_path)
    source = tmp_path / "out.docx"
    source.write_bytes(b"bytes")
    artifact_name = store.store_artifact("task-1", source, "out.docx")
    store.set("task-1", {"status": "done", "artifact": artifact_name})

    reopened = TaskStore(tmp_path)
    task = reopened.get("task-1")
    assert task is not None
    assert task["status"] == "done"
    result = reopened.result_path("task-1", task["artifact"])
    assert result is not None
    assert result.read_bytes() == b"bytes"
