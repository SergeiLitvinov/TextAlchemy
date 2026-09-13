"""Индивидуальные настройки пакета проверяются до очереди и переживают перезапуск."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from textalchemy.web.main import app
from textalchemy.web.queue import task_queue
from textalchemy.web.routes import convert as facade
from textalchemy.web.tasks import TaskStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TaskStore:
    storage = TaskStore(tmp_path / "tasks")
    monkeypatch.setattr(facade, "tasks_store", storage)
    monkeypatch.setattr(importlib.import_module("textalchemy.web.app"), "tasks_store", storage)
    yield storage
    assert task_queue.wait_idle(timeout=30)


def _files() -> list:
    return [("files", ("same.txt", b"First", "text/plain")), ("files", ("same.txt", b"Second", "text/plain"))]


def test_individual_targets_and_modes_survive_rerun(store: TaskStore) -> None:
    client = TestClient(app)
    options = [{"target_format": "model", "mode": "editable"}, {"target_format": "html", "mode": "balanced"}]
    response = client.post(
        "/api/convert/batch", files=_files(), data={"target_format": "docx", "file_options": json.dumps(options)}
    )
    assert response.status_code == 200, response.text
    created = response.json()
    for cycle in range(2):
        assert task_queue.wait_idle(timeout=30)
        for item, expected in zip(created["tasks"], options):
            task = store.get(item["task_id"])
            assert task["status"] == "done", task
            assert task["target_format"] == expected["target_format"]
            assert task["mode"] == expected["mode"]
            assert store.result_path(item["task_id"], task["artifact"]).is_file()
        if cycle == 0:
            assert len(client.post(f"/api/convert/jobs/{created['job_id']}/rerun").json()["launched"]) == 2


@pytest.mark.parametrize(
    "options",
    [
        "oops",
        "{}",
        "[]",
        "[{}, null]",
        '[{}, {"mode": 3}]',
        '[{}, {"unknown": 1}]',
        '[{}, {"mode": "faithful", "target_format": "pptx"}]',
    ],
)
def test_invalid_options_do_not_queue_partial_batch(store: TaskStore, options: str) -> None:
    response = TestClient(app).post(
        "/api/convert/batch", files=_files(), data={"target_format": "model", "file_options": options}
    )
    assert response.status_code == 400
    assert store.list_jobs() == []
    assert not list(store.root.glob("*.json"))


@pytest.mark.parametrize("status", ["error", "interrupted", "cancelled", "queued", "running", "cancelling"])
def test_retry_failed_preserves_completed_results(store: TaskStore, status: str) -> None:
    client = TestClient(app)
    response = client.post("/api/convert/batch", files=_files(), data={"target_format": "model"})
    created = response.json()
    assert task_queue.wait_idle(timeout=30)
    good_id, failed_id = [item["task_id"] for item in created["tasks"]]
    good = store.get(good_id)
    good_bytes = store.result_path(good_id, good["artifact"]).read_bytes()
    bad = store.get(failed_id)
    store.set(failed_id, {**bad, "status": status, "mode": "editable"})
    result = client.post(f"/api/convert/jobs/{created['job_id']}/rerun", data={"failed_only": "true"})
    assert result.status_code == 200
    assert result.json()["failed_only"] is True
    expected = [failed_id] if status in {"error", "interrupted", "cancelled"} else []
    assert result.json()["launched"] == expected
    assert task_queue.wait_idle(timeout=30)
    assert store.get(good_id) == good
    assert store.result_path(good_id, good["artifact"]).read_bytes() == good_bytes
    assert store.get(failed_id)["mode"] == "editable"
    if expected:
        assert store.get(failed_id)["status"] == "done"


def test_retry_failed_without_source_does_not_clear_result(store: TaskStore) -> None:
    client = TestClient(app)
    created = client.post("/api/convert/batch", files=_files(), data={"target_format": "model"}).json()
    assert task_queue.wait_idle(timeout=30)
    failed_id = created["tasks"][0]["task_id"]
    task = store.get(failed_id)
    store.set(failed_id, {**task, "status": "error"})
    store.source_path(failed_id).unlink()
    before = store.get(failed_id)
    response = client.post(f"/api/convert/jobs/{created['job_id']}/rerun", data={"failed_only": "true"})
    assert response.json()["launched"] == []
    assert store.get(failed_id) == before
    assert store.result_path(failed_id, task["artifact"]).is_file()
