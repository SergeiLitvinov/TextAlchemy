"""A real uploaded self-contained HTML file reaches the shared conversion service."""

import importlib
from pathlib import Path

import pytest

pytest.importorskip("bs4")
pytest.importorskip("tinycss2")
from fastapi.testclient import TestClient

from textalchemy.web.main import app
from textalchemy.web.queue import task_queue
from textalchemy.web.routes import convert as facade
from textalchemy.web.tasks import TaskStore


@pytest.mark.parametrize("fixture", ["scientific-html.html", "html-warnings.html"])
def test_html_upload_to_model(tmp_path, monkeypatch, fixture):
    storage = TaskStore(tmp_path / "tasks")
    monkeypatch.setattr(facade, "tasks_store", storage)
    monkeypatch.setattr(importlib.import_module("textalchemy.web.app"), "tasks_store", storage)
    client = TestClient(app)
    source = (Path(__file__).parent / "corpus" / fixture).read_bytes()
    try:
        response = client.post(
            "/api/convert", data={"source_format": "html", "target_format": "model"},
            files={"file": ("scientific.html", source, "text/html")},
        )
        assert response.status_code == 200, response.text
        assert task_queue.wait_idle(timeout=30)
        task = storage.get(response.json()["task_id"])
        assert task["status"] == "done", task
        assert task["report"]["metrics"]["executed_steps"] == ["html.model"]
        if fixture == "html-warnings.html":
            restored = TaskStore(tmp_path / "tasks").get(response.json()["task_id"])
            report = restored["report"]
            locations = report["metrics"]["step_metrics"]["html.model"]["html_locations"]
            assert len(locations) == 3
            assert all(issue["location"] in locations for issue in report["issues"])
            assert locations["html:document"]["label"] == "Весь документ"
    finally:
        assert task_queue.wait_idle(timeout=30)
