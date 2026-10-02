"""Пакетные сценарии без HTTP: реальные исходники, сохранение и отказы."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.test_web_ingest_services import BytesUpload
from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.web.queue import TaskQueue, recover_persisted_tasks
from textalchemy.web.services.batch_history import BatchHistoryService
from textalchemy.web.services.batch_retry import BatchRetryService, retry_saved_task, submit_saved_tasks
from textalchemy.web.services.batch_submission import BatchSettings, BatchSubmissionService
from textalchemy.web.services.conversion_tasks import ConversionTaskService
from textalchemy.web.tasks import TaskStore


@pytest.fixture
def services(tmp_path: Path) -> tuple[TaskStore, BatchSubmissionService, ConversionTaskService, TaskQueue]:
    store = TaskStore(tmp_path / "store")
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    factory = lambda: ArtifactWorkspace(parent=workspace_root)  # noqa: E731
    queue = TaskQueue(max_workers=1)
    tasks = ConversionTaskService(store=store, queue=queue, workspace_factory=factory)
    batch = BatchSubmissionService(store=store, persist=tasks.persist, resume=tasks.resume, workspace_factory=factory)
    yield store, batch, tasks, queue
    queue.shutdown(wait=True)
    assert list(workspace_root.iterdir()) == []


def uploads() -> list[BytesUpload]:
    return [BytesUpload("Отчёт.txt", b"First source"), BytesUpload("Отчёт.txt", b"Second source")]


def test_real_batch_and_history_preserve_same_names_individual_settings_and_results(services: tuple) -> None:
    store, batch, tasks, queue = services
    options = [{"target_format": "model", "mode": "editable"}, {"target_format": "html", "mode": "balanced"}]

    def resume(task_id: str) -> None:
        # Пакет уже виден в хранилище до первого обращения к очереди.
        assert len(store.list_jobs()) == 1
        tasks.resume(task_id)

    batch = replace(batch, resume=resume)
    created = asyncio.run(batch.submit(uploads(), settings=BatchSettings(max_loss_issues=100), file_options=json.dumps(options)))
    assert queue.wait_idle(timeout=30)
    history = BatchHistoryService(store, lambda task: {key: value for key, value in task.items() if key != "artifact"})
    assert history.list()["jobs"][0]["counts"]["done"] == 2
    for item, option, expected in zip(created["tasks"], options, (b"First source", b"Second source")):
        task = store.get(item["task_id"])
        assert task["status"] == "done", task
        assert task["mode"] == option["mode"] and task["target_format"] == option["target_format"]
        assert task["max_loss_issues"] == 100
        assert store.source_path(item["task_id"]).read_bytes() == expected
        result = store.result_path(item["task_id"], task["artifact"])
        assert expected.decode() in result.read_text(encoding="utf-8")
    assert all("artifact" not in item for item in history.get(created["job_id"])["tasks"])
    history.delete(created["job_id"])
    assert store.list_jobs() == [] and store.list_tasks() == []


@pytest.mark.parametrize("failure", ["task", "job"])
def test_partial_persistence_rolls_back_new_batch_without_starting_queue(
    services: tuple,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    store, batch, tasks, _queue = services
    launched = []
    batch = replace(batch, resume=launched.append)
    if failure == "task":
        calls = 0

        def fail_after_copy(*args: Any) -> None:
            nonlocal calls
            tasks.persist(*args)
            calls += 1
            if calls == 2:
                raise OSError("task persistence failed after copy")

        batch = replace(batch, persist=fail_after_copy)
    else:
        original = store.set_job

        def fail_after_job(job_id: str, payload: dict[str, Any]) -> None:
            original(job_id, payload)
            raise OSError("job persistence failed after write")

        monkeypatch.setattr(store, "set_job", fail_after_job)
    with pytest.raises(OSError, match="persistence failed"):
        asyncio.run(batch.submit(uploads(), settings=BatchSettings(target_format="model")))
    assert launched == [] and store.list_jobs() == [] and store.list_tasks() == []
    assert not list(store.root.glob("*/source/*"))


def test_partial_upload_leaves_no_sources_or_tasks(services: tuple) -> None:
    store, batch, _tasks, _queue = services

    class BrokenUpload(BytesUpload):
        async def read(self, size: int = -1) -> bytes:
            if self.offset:
                raise OSError("upload interrupted")
            return await super().read(size)

    with pytest.raises(OSError, match="upload interrupted"):
        asyncio.run(
            batch.submit([uploads()[0], BrokenUpload("broken.txt", b"partial")], settings=BatchSettings(target_format="model"))
        )
    assert store.list_tasks() == [] and store.list_jobs() == []


@pytest.mark.parametrize("note_fails", [False, True])
def test_closed_queue_keeps_batch_inputs_and_policies_and_recovers(
    services: tuple, monkeypatch: pytest.MonkeyPatch, note_fails: bool
) -> None:
    store, batch, _tasks, queue = services
    queue.shutdown(wait=True)
    if note_fails:

        def fail_note(*_args: Any) -> None:
            raise OSError("cannot write explanation")

        monkeypatch.setattr(store, "note_queue_failure", fail_note)
    settings = BatchSettings(
        target_format="model",
        mode="editable",
        max_loss_issues=3,
        max_lost_objects=2,
        require_unchanged_text=True,
        max_changed_formulas=0,
        max_changed_emphasis=0,
    )
    created = asyncio.run(batch.submit(uploads(), settings=settings))
    restored = TaskStore(store.root)
    for item, expected in zip(created["tasks"], (b"First source", b"Second source")):
        task = restored.get(item["task_id"])
        assert task["status"] == "queued" and task["mode"] == "editable"
        assert task["max_loss_issues"] == 3 and task["max_lost_objects"] == 2
        assert task["require_unchanged_text"] and task["max_changed_formulas"] == 0 and task["max_changed_emphasis"] == 0
        assert restored.source_path(item["task_id"]).read_bytes() == expected
    recovery_queue = TaskQueue(max_workers=1)
    try:
        recovery = ConversionTaskService(store=restored, queue=recovery_queue, workspace_factory=batch.workspace_factory)
        recover_persisted_tasks(restored, {"convert": recovery.resume})
        assert recovery_queue.wait_idle(timeout=30)
        assert all(restored.get(item["task_id"])["status"] == "done" for item in created["tasks"])
    finally:
        recovery_queue.shutdown(wait=True)


@pytest.mark.parametrize("individual", [False, True])
def test_retry_metadata_failure_preserves_original_result_and_source(
    services: tuple, monkeypatch: pytest.MonkeyPatch, individual: bool
) -> None:
    store, batch, tasks, queue = services
    created = asyncio.run(batch.submit(uploads(), settings=BatchSettings(target_format="model")))
    assert queue.wait_idle(timeout=30)
    task_id = created["tasks"][0]["task_id"]
    original = store.get(task_id)
    result = store.result_path(task_id, original["artifact"])
    before = result.read_bytes()
    source = store.source_path(task_id).read_bytes()
    old_write = store._write_meta_locked

    def fail_retry(identifier: str, payload: dict[str, Any]) -> None:
        if identifier == task_id and payload.get("status") == "queued":
            raise OSError("metadata write failed")
        old_write(identifier, payload)

    monkeypatch.setattr(store, "_write_meta_locked", fail_retry)
    if individual:
        with pytest.raises(OSError, match="metadata write failed"):
            tasks.rerun(task_id)
    else:
        retried = BatchRetryService(store, tasks.resume).rerun(created["job_id"])
        assert retried["skipped"][0]["task_id"] == task_id
        assert "прежний результат сохранён" in retried["skipped"][0]["reason"]
        assert retried["launched"] == [created["tasks"][1]["task_id"]]
        assert queue.wait_idle(timeout=30)
    assert store.get(task_id) == original and result.read_bytes() == before
    assert store.source_path(task_id).read_bytes() == source


def test_selected_retry_queue_failure_leaves_other_results_unchanged(services: tuple) -> None:
    store, batch, tasks, queue = services
    created = asyncio.run(batch.submit(uploads(), settings=BatchSettings(target_format="html", mode="editable")))
    assert queue.wait_idle(timeout=30)
    good_id, failed_id = [item["task_id"] for item in created["tasks"]]
    good = store.get(good_id)
    good_result = store.result_path(good_id, good["artifact"]).read_bytes()
    store.set(failed_id, {**store.get(failed_id), "status": "error"})
    queue.shutdown(wait=True)
    result = BatchRetryService(store, tasks.resume).rerun(created["job_id"], task_ids=json.dumps([failed_id]))
    assert result["queued"] == [failed_id] and result["launched"] == []
    assert store.get(failed_id)["status"] == "queued" and store.get(failed_id)["mode"] == "editable"
    assert store.source_path(failed_id).read_bytes() == b"Second source"
    assert store.get(good_id) == good and store.result_path(good_id, good["artifact"]).read_bytes() == good_result


def test_queue_error_does_not_overwrite_task_completed_during_submission(services: tuple) -> None:
    store, batch, tasks, _queue = services
    created = asyncio.run(
        replace(batch, resume=lambda _task_id: None).submit(uploads(), settings=BatchSettings(target_format="model"))
    )
    task_id = created["tasks"][0]["task_id"]

    def complete_then_raise(identifier: str) -> None:
        tasks.run_stored(identifier)
        raise RuntimeError("queue reported an error after completion")

    assert submit_saved_tasks(store, [task_id], resume=complete_then_raise) == []
    assert store.get(task_id)["status"] == "done" and store.get(task_id)["error"] is None


def test_single_retry_rejects_state_changed_before_commit(services: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    store, batch, tasks, queue = services
    created = asyncio.run(batch.submit(uploads(), settings=BatchSettings(target_format="model")))
    assert queue.wait_idle(timeout=30)
    task_id = created["tasks"][0]["task_id"]
    prepare = store.prepare_retry

    def changed(identifier: str, **kwargs: Any) -> bool:
        store.set(identifier, {**store.get(identifier), "status": "running"})
        return prepare(identifier, **kwargs)

    monkeypatch.setattr(store, "prepare_retry", changed)
    with pytest.raises(ValueError, match="Состояние"):
        retry_saved_task(store, task_id, resume=tasks.resume)
    assert store.get(task_id)["status"] == "running"


def test_cleanup_failure_after_retry_commit_does_not_strand_queued_task(services: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    store, batch, tasks, queue = services
    created = asyncio.run(batch.submit(uploads(), settings=BatchSettings(target_format="model")))
    assert queue.wait_idle(timeout=30)
    task_id = created["tasks"][0]["task_id"]
    old = store.get(task_id)
    previous_result = store.result_path(task_id, old["artifact"])
    original = previous_result.read_bytes()
    launched = []

    def fail_cleanup(_identifier: str) -> None:
        raise OSError("result temporarily locked")

    monkeypatch.setattr(store, "_clear_result_locked", fail_cleanup)
    retry_saved_task(store, task_id, resume=launched.append)
    assert launched == [task_id] and store.get(task_id)["status"] == "queued"
    assert store.get(task_id)["artifact"] is None and previous_result.read_bytes() == original
    tasks.run_stored(task_id)
    assert store.get(task_id)["status"] == "done"


def test_individual_retry_closed_queue_keeps_source_and_settings(services: tuple) -> None:
    store, batch, tasks, queue = services
    created = asyncio.run(batch.submit(uploads(), settings=BatchSettings(target_format="model", mode="editable")))
    assert queue.wait_idle(timeout=30)
    queue.shutdown(wait=True)
    task_id = created["tasks"][0]["task_id"]
    assert tasks.rerun(task_id) == {"task_id": task_id, "status": "queued"}
    assert store.get(task_id)["mode"] == "editable" and "Ожидает перезапуска очереди" in store.get(task_id)["error"]
    assert store.source_path(task_id).read_bytes() == b"First source"
