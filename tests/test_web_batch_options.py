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


def _mixed_batch(store: TaskStore) -> tuple[dict, list[str]]:
    files = [("files", (name, name.encode(), "text/plain")) for name in ("good.txt", "retry.txt", "leave.txt")]
    created = TestClient(app).post("/api/convert/batch", files=files, data={"target_format": "model"}).json()
    assert task_queue.wait_idle(timeout=30)
    ids = [item["task_id"] for item in created["tasks"]]
    for task_id in ids[1:]:
        store.set(task_id, {**store.get(task_id), "status": "error", "error": "Temporary failure"})
    return created, ids


@pytest.mark.parametrize("status", ["error", "interrupted", "cancelled", "done", "queued", "running", "cancelling"])
def test_retry_selected_preserves_other_files(store: TaskStore, status: str) -> None:
    created, ids = _mixed_batch(store)
    store.set(ids[1], {**store.get(ids[1]), "status": status, "mode": "editable", "max_loss_issues": 2})
    snapshots = [store.get(task_id) for task_id in ids]
    artifacts = [store.result_path(task_id, task["artifact"]).read_bytes() for task_id, task in zip(ids, snapshots)]
    response = TestClient(app).post(
        f"/api/convert/jobs/{created['job_id']}/rerun", data={"task_ids": json.dumps([ids[1]])},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    eligible = status in {"error", "interrupted", "cancelled"}
    assert payload["launched"] == ([ids[1]] if eligible else [])
    assert payload["queued"] == payload["launched"]
    assert payload["failed_only"] is True
    assert [item["task_id"] for item in payload["skipped"]] == ([] if eligible else [ids[1]])
    assert task_queue.wait_idle(timeout=30)
    for index in (0, 2) if eligible else (0, 1, 2):
        assert store.get(ids[index]) == snapshots[index]
        assert store.result_path(ids[index], snapshots[index]["artifact"]).read_bytes() == artifacts[index]
    if eligible:
        assert store.get(ids[1])["status"] == "done"
        assert store.get(ids[1])["mode"] == "editable"
        assert store.get(ids[1])["max_loss_issues"] == 2


@pytest.mark.parametrize("selection", ["", "[]", "null", "{}", "[1]", "invalid", "foreign", "duplicate"])
def test_invalid_retry_selection_has_no_side_effects(store: TaskStore, selection: str) -> None:
    created, ids = _mixed_batch(store)
    if selection == "foreign":
        selection = json.dumps([ids[1], "foreign-task"])
    elif selection == "duplicate":
        selection = json.dumps([ids[1], ids[1]])
    before = [store.get(task_id) for task_id in ids]
    response = TestClient(app).post(f"/api/convert/jobs/{created['job_id']}/rerun", data={"task_ids": selection})
    assert response.status_code == 400, response.text
    assert [store.get(task_id) for task_id in ids] == before
    assert all(store.result_path(task_id, task["artifact"]).is_file() for task_id, task in zip(ids, before))


def test_retry_selection_rechecks_status_before_clearing(store: TaskStore, monkeypatch: pytest.MonkeyPatch) -> None:
    created, ids = _mixed_batch(store)
    original = store.prepare_retry
    task = store.get(ids[1])
    artifact = store.result_path(ids[1], task["artifact"])
    content = artifact.read_bytes()

    def change_before_retry(task_id, **kwargs):
        store.set(task_id, {**store.get(task_id), "status": "done"})
        return original(task_id, **kwargs)

    monkeypatch.setattr(store, "prepare_retry", change_before_retry)
    response = TestClient(app).post(
        f"/api/convert/jobs/{created['job_id']}/rerun", data={"task_ids": json.dumps([ids[1]])},
    ).json()
    assert response["launched"] == []
    assert response["skipped"][0]["task_id"] == ids[1]
    assert store.get(ids[1])["status"] == "done"
    assert artifact.read_bytes() == content


def test_retry_selected_without_source_is_explained(store: TaskStore) -> None:
    created, ids = _mixed_batch(store)
    store.source_path(ids[1]).unlink()
    before = store.get(ids[1])
    response = TestClient(app).post(
        f"/api/convert/jobs/{created['job_id']}/rerun", data={"task_ids": json.dumps([ids[1]])},
    ).json()
    assert response["queued"] == []
    assert response["skipped"][0]["reason"] == "Исходный файл недоступен"
    assert store.get(ids[1]) == before


def test_retry_selected_stays_queued_if_queue_unavailable(store: TaskStore, monkeypatch: pytest.MonkeyPatch) -> None:
    created, ids = _mixed_batch(store)

    def unavailable(task_id):
        raise RuntimeError("Queue unavailable")

    monkeypatch.setattr(facade, "resume_conversion_task", unavailable)
    response = TestClient(app).post(
        f"/api/convert/jobs/{created['job_id']}/rerun", data={"task_ids": json.dumps([ids[1]])},
    ).json()
    assert response["queued"] == [ids[1]]
    assert response["launched"] == []
    assert store.get(ids[1])["status"] == "queued"
    assert store.get(ids[2])["status"] == "error"
