"""Быстрый HTML-просмотр не запускает офисный движок и не засоряет историю задач."""

import json
from pathlib import Path
from typing import Any

import pytest

from tests import test_web_generator_services as service_fixtures
from tests import test_web_m4_completion as acceptance
from textalchemy.web.services.live_preview import LivePreviewService

generator, m4_client = service_fixtures.generator, acceptance.m4_client


def test_live_preview_validates_and_cleans_workspace(generator: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def office_forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Быстрый просмотр не должен запускать офисный движок")

    monkeypatch.setattr("textalchemy.web.preview.cached_page_count", office_forbidden)
    service = LivePreviewService(
        resolve_template=generator.resolve_template,
        schema_provider=generator.schema_provider,
        workspace_factory=generator.workspace_factory,
    )
    before = {path.name for path in tmp_path.iterdir()}
    result = service.preview(template="sample", params=json.dumps({"title": "<script>unsafe</script>"}))
    assert result["success"]
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in result["html"]
    assert "<script>unsafe" not in result["html"]
    assert {path.name for path in tmp_path.iterdir()} == before
    invalid = service.preview(template="sample", params="[]")
    assert not invalid["success"]
    missing = service.preview(template="sample")
    assert missing["draft"]
    assert missing["missing_fields"][0]["name"] == "title"
    source = service.preview(template="sample", source=True)
    assert "{{ title }}" in source["html"]
    assert {path.name for path in tmp_path.iterdir()} == before


def test_live_preview_api_keeps_history_and_source_intact(m4_client: Any) -> None:
    client, _ = m4_client
    template = acceptance.import_sample(client)
    before = client.get("/api/tasks").json()["tasks"]
    response = client.post("/api/generate/live-preview", data={"template": template})
    assert response.status_code == 200
    assert response.json()["success"]
    assert "Иванов" in response.json()["html"]
    assert client.get("/api/tasks").json()["tasks"] == before
    assert client.post("/api/generate/live-preview", data={"template": template, "source": "true"}).json()["success"]
    assert not client.post("/api/generate/live-preview", data={"template": "missing"}).json()["success"]
