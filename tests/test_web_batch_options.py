"""Индивидуальные настройки пакета проверяются до очереди и переживают перезапуск."""

from __future__ import annotations

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
