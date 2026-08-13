"""Тесты web.tasks и web.queue — on-disk хранилище и in-process очередь."""

from __future__ import annotations

import time
import zipfile

import pytest

from textalchemy.web.queue import (
    INTERRUPTED_MESSAGE,
    INTERRUPTED_STATUS,
    TaskQueue,
    recover_interrupted_tasks,
    recover_persisted_tasks,
)
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
    preview = store.preview_dir("task-1")
    (preview / "target-0-72dpi.png").write_bytes(b"stale")
    stored_name = store.store_artifact("task-1", source, "result.docx")
    assert stored_name == "result.docx"
    assert not preview.exists()
    result = store.result_path("task-1", stored_name)
    assert result is not None
    assert result.read_bytes() == b"artifact-bytes"


def test_storage_bytes_counts_metadata_sources_previews_and_results(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-bytes")
    store.set("task-1", {"status": "done"})
    store.store_source("task-1", source, "source.pdf")
    store.store_artifact("task-1", source, "result.pdf")
    preview = store.preview_dir("task-1")
    (preview / "page.png").write_bytes(b"preview")

    expected = sum(path.stat().st_size for path in store.root.rglob("*") if path.is_file())
    assert store.storage_bytes() == expected


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


def test_store_artifact_directory_keeps_previous_zip_when_archiving_fails(tmp_path, monkeypatch):
    store = TaskStore(tmp_path)
    source_dir = tmp_path / "html"
    source_dir.mkdir()
    (source_dir / "index.html").write_text("old", encoding="utf-8")
    stored_name = store.store_artifact("task-1", source_dir, "deck-html")
    previous = store.result_path("task-1", stored_name).read_bytes()

    def fail_archive(*_args, **_kwargs):
        raise OSError("archive failed")

    monkeypatch.setattr("textalchemy.web.tasks.shutil.make_archive", fail_archive)
    with pytest.raises(OSError, match="archive failed"):
        store.store_artifact("task-1", source_dir, "deck-html")

    assert store.result_path("task-1", stored_name).read_bytes() == previous
    assert not list((tmp_path / "task-1").glob("*.partial.zip"))


def test_result_path_rejects_traversal(tmp_path):
    store = TaskStore(tmp_path)
    assert store.result_path("task-1", "../outside.txt") is None


@pytest.mark.parametrize("identifier", ["../outside", "a/b", "a\\b", ".", ""])
def test_task_identifier_rejects_path_traversal(tmp_path, identifier):
    store = TaskStore(tmp_path)
    with pytest.raises(ValueError, match="invalid task identifier"):
        store.set(identifier, {"status": "done"})
    assert store.get(identifier) is None
    assert store.source_path(identifier) is None
    assert store.result_path(identifier, "result.bin") is None
    store.delete(identifier)


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


def test_list_tasks_returns_fresh_first_with_task_id(tmp_path):
    store = TaskStore(tmp_path)
    store.set("first", {"status": "running", "mode": "balanced"})
    time.sleep(0.01)
    store.set("second", {"status": "done"})

    tasks = store.list_tasks()
    assert [task["task_id"] for task in tasks] == ["second", "first"]
    assert tasks[0]["status"] == "done"
    assert tasks[1]["mode"] == "balanced"


def test_list_tasks_skips_stale_and_excludes_jobs(tmp_path, monkeypatch):
    store = TaskStore(tmp_path, ttl_seconds=10)
    store.set("stale", {"status": "done"})
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 60)
    assert store.list_tasks() == []  # протухшие удалены ленивой чисткой

    store.set("fresh", {"status": "done"})
    store.set_job("job-1", {"target_format": "docx"})
    assert [task["task_id"] for task in store.list_tasks()] == ["fresh"]


def test_list_tasks_empty_and_limited(tmp_path):
    store = TaskStore(tmp_path)
    assert store.list_tasks() == []
    for index in range(3):
        store.set(f"task-{index}", {"status": "done"})
    assert len(store.list_tasks(limit=2)) == 2


def test_recover_interrupted_marks_only_running(tmp_path):
    store = TaskStore(tmp_path)
    store.set("running-1", {"status": "running", "mode": "balanced"})
    store.set("running-2", {"status": "running", "target_format": "html"})
    store.set("done-1", {"status": "done", "artifact": "out.docx"})
    store.set("error-1", {"status": "error", "error": "boom"})

    assert recover_interrupted_tasks(store) == 2

    running = store.get("running-1")
    assert running["status"] == INTERRUPTED_STATUS
    assert running["error"] == INTERRUPTED_MESSAGE
    assert running["mode"] == "balanced"
    assert store.get("running-2")["status"] == INTERRUPTED_STATUS
    assert store.get("done-1")["status"] == "done"
    assert store.get("error-1")["status"] == "error"
    assert store.get("done-1")["artifact"] == "out.docx"


def test_recover_interrupted_is_idempotent(tmp_path):
    store = TaskStore(tmp_path)
    store.set("running-1", {"status": "running"})
    assert recover_interrupted_tasks(store) == 1
    assert store.get("running-1")["status"] == INTERRUPTED_STATUS
    assert recover_interrupted_tasks(store) == 0
    assert store.get("running-1")["status"] == INTERRUPTED_STATUS


def test_recover_interrupted_is_not_limited_to_history_page(tmp_path):
    store = TaskStore(tmp_path)
    for index in range(105):
        store.set(f"running-{index}", {"status": "running"})

    assert recover_interrupted_tasks(store) == 105
    assert all(task["status"] == INTERRUPTED_STATUS for task in store.list_tasks(limit=None))


def test_recover_persisted_tasks_resumes_known_queue_kind(tmp_path):
    store = TaskStore(tmp_path)
    store.set("queued-1", {"status": "queued", "queue_kind": "convert"})
    resumed = []

    summary = recover_persisted_tasks(store, {"convert": resumed.append})

    assert resumed == ["queued-1"]
    assert summary.resumed == 1
    assert summary.interrupted == 0
    assert store.get("queued-1")["status"] == "queued"


def test_recover_persisted_tasks_interrupts_unknown_or_broken_handler(tmp_path):
    store = TaskStore(tmp_path)
    store.set("unknown", {"status": "running", "queue_kind": "unknown"})
    store.set("broken", {"status": "queued", "queue_kind": "convert"})

    def fail(_task_id):
        raise RuntimeError("cannot resume")

    summary = recover_persisted_tasks(store, {"convert": fail})

    assert summary.resumed == 0
    assert summary.interrupted == 2
    assert store.get("unknown")["status"] == INTERRUPTED_STATUS
    assert store.get("broken")["status"] == INTERRUPTED_STATUS


def test_task_queue_runs_tasks_and_waits_for_idle():
    queue = TaskQueue(max_workers=1)
    try:
        results = []

        def record(value):
            results.append(value)

        queue.submit(record, 1)
        queue.submit(record, 2)
        assert queue.pending() >= 1
        assert queue.wait_idle(timeout=5) is True
        assert results == [1, 2]
        assert queue.pending() == 0
    finally:
        queue.shutdown(wait=True)


def test_task_queue_survives_failing_task():
    queue = TaskQueue(max_workers=1)
    try:

        def boom():
            raise RuntimeError("worker must survive")

        queue.submit(boom)
        queue.submit(lambda: None)
        assert queue.wait_idle(timeout=5) is True
    finally:
        queue.shutdown(wait=True)


def test_task_queue_submit_after_shutdown_does_not_leak_pending_count():
    queue = TaskQueue(max_workers=1)
    queue.shutdown(wait=True)

    with pytest.raises(RuntimeError):
        queue.submit(lambda: None)

    assert queue.pending() == 0
    assert queue.wait_idle(timeout=0) is True


def test_named_task_can_be_cancelled_before_it_starts():
    queue = TaskQueue(max_workers=1)
    gate = __import__("threading").Event()
    try:
        queue.submit(lambda: gate.wait(2))
        future = queue.submit_named("cancel-me", lambda: pytest.fail("cancelled task ran"))

        assert queue.cancel("cancel-me") is True
        gate.set()
        assert queue.wait_idle(timeout=5) is True
        assert future.cancelled() is True
        assert queue.pending() == 0
    finally:
        gate.set()
        queue.shutdown(wait=True)


def test_clear_result_preserves_source_for_rerun(tmp_path):
    store = TaskStore(tmp_path)
    task_dir = tmp_path / "rerunnable"
    source_dir = task_dir / "source"
    source_dir.mkdir(parents=True)
    (source_dir / "input.pdf").write_bytes(b"source")
    (task_dir / "output.docx").write_bytes(b"result")
    (task_dir / "preview").mkdir()

    store.clear_result("rerunnable")

    assert store.source_path("rerunnable").read_bytes() == b"source"
    assert not (task_dir / "output.docx").exists()
    assert not (task_dir / "preview").exists()
