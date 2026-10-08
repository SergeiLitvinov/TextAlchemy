"""Пользовательский EPUB-маршрут без прежних EbookLib/lxml требований."""

import builtins
from pathlib import Path
from typing import Any

import pytest

from tests import test_web_m4_completion as fixtures
from tests.test_formats.test_epub_model import _rich_epub
from textalchemy.core.document_codec import document_from_json
from textalchemy.web.queue import task_queue

m4_client = fixtures.m4_client


@pytest.mark.parametrize("target", ["model", "html"])
def test_web_epub_conversion_and_retry_without_legacy_backends(
    m4_client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    """Каталог, конвертация и повтор используют опубликованный нативный обработчик."""
    client, store = m4_client
    source = tmp_path / "book.epub"
    _rich_epub(source)
    original = source.read_bytes()
    real_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.split(".", 1)[0] in {"ebooklib", "lxml"}:
            raise AssertionError(f"EPUB route attempted legacy import: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    catalog = client.get("/api/convert/capabilities").json()
    epub_source = next(item for item in catalog["sources"] if item["format"] == "epub")
    assert target in {item["format"] for item in epub_source["targets"]}
    response = client.post(
        "/api/convert", files={"file": (source.name, original)}, data={"target_format": target}
    )
    assert response.status_code == 200, response.text
    created = response.json()
    for cycle in range(2):
        assert task_queue.wait_idle(timeout=30)
        task = store.get(created["task_id"])
        assert task["status"] == "done", task
        result = client.get(created["result"])
        assert result.status_code == 200
        if target == "model":
            sections = document_from_json(result.text).sections
            assert [section.properties["epub"]["title"] for section in sections] == ["Second", "First"]
        else:
            assert 'href="#epub-chapters-first.xhtml--target"' in result.text
            assert 'id="epub-chapters-first.xhtml--target"' in result.text
            assert "data:image/png;base64," in result.text
        if cycle == 0:
            assert client.post(f"/api/tasks/{created['task_id']}/rerun").status_code == 200
    assert source.read_bytes() == original
