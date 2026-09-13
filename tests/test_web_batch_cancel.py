"""Отмена пакета пропускает готовые результаты и остаётся повторяемой."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from textalchemy.web.main import app
from textalchemy.web.routes import convert as facade
from textalchemy.web.services.batch_actions import cancel_batch
from textalchemy.web.tasks import TaskStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TaskStore:
    store = TaskStore(tmp_path / "tasks")
    monkeypatch.setattr(facade, "tasks_store", store)
    source = tmp_path / "ready.txt"
    source.write_text("Completed", encoding="utf-8")
    artifact = store.store_artifact("done", source, "ready.txt")
    store.set("done", {"status": "done", "artifact": artifact})
    for task_id in ("queued", "running", "cancelling", "error", "cancelled"):
        store.set(task_id, {"status": task_id})
    store.set_job(
        "batch",
        {
            "files": [
                {"task_id": item}
                for item in (
                    "done",
                    "queued",
                    "running",
                    "cancelling",
                    "error",
                    "cancelled",
                    "expired",
                )
            ]
        },
    )
    return store


def test_cancel_batch_preserves_done_and_skips_terminal_tasks(store: TaskStore) -> None:
    client = TestClient(app)
    before = store.get("done")
    result = client.post("/api/convert/jobs/batch/cancel")
    assert result.status_code == 200
    assert result.json()["requested"] == [
        {"task_id": "queued", "status": "cancelled"},
        {"task_id": "running", "status": "cancelling"},
    ]
    assert store.get("done") == before
    assert store.result_path("done", before["artifact"]).read_text() == "Completed"
    assert store.get("error")["status"] == "error"
    assert client.post("/api/convert/jobs/batch/cancel").json()["requested"] == []
    assert client.post("/api/convert/jobs/unknown/cancel").status_code == 404


def test_task_completed_between_checks_is_skipped(store: TaskStore) -> None:
    called = []

    def cancel(task_id: str) -> dict:
        called.append(task_id)
        if task_id == "queued":
            raise ValueError("Already completed")
        raise KeyError(task_id)

    result = cancel_batch(store, "batch", cancel_task=cancel)
    assert called == ["queued", "running"]
    assert result["requested"] == []
    assert len(result["skipped"]) == 7
