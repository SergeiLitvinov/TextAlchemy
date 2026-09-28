"""Persistence, version conflicts and actual file exports for the OCR text editor."""

import importlib
import io
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from textalchemy.core.document_codec import document_from_dict
from textalchemy.web.services import ocr_drafts
from textalchemy.web.tasks import TaskStore


@pytest.fixture
def draft(tmp_path, monkeypatch):
    web = importlib.import_module("textalchemy.web.app")
    store = TaskStore(tmp_path / "tasks")
    monkeypatch.setattr(web, "tasks_store", store)
    engine = SimpleNamespace(is_available=True, backend_name="test",
                             recognize=lambda *a, **kw: SimpleNamespace(text="0шибка\n", confidence=0.8))
    monkeypatch.setattr("textalchemy.web.routes.recognize.OcrEngine", lambda **kw: engine)
    with TestClient(web.app) as client:
        response = client.post("/api/recognize", files={"file": ("page.png", b"fixture", "image/png")})
        assert response.json()["success"]
        yield client, "/api/recognize/drafts/" + response.json()["draft_id"], store


@pytest.mark.parametrize("format", ["txt", "docx", "pdf", "model"])
def test_saved_text_survives_reload_and_export(draft, format):
    client, url, store = draft
    text = "Исправленный текст\n\nСтрока 2\n"
    response = client.put(url, json={"text": text, "revision": 1})
    assert response.status_code == 200
    assert response.json()["revision"] == 2
    restored = ocr_drafts.get_draft(ocr_drafts.draft_store(TaskStore(store.root)), url.rsplit("/", 1)[1])
    assert restored["text"] == text
    assert client.get(url).json()["text"] == text
    exported = client.get(url + "/export", params={"format": format, "revision": 2})
    assert exported.status_code == 200
    assert exported.headers["x-document-revision"] == "2"
    if format == "txt":
        assert exported.content.decode("utf-8") == text
    elif format == "docx":
        from docx import Document

        assert "\n".join(p.text for p in Document(io.BytesIO(exported.content)).paragraphs) == text
    elif format == "pdf":
        import fitz

        with fitz.open(stream=exported.content, filetype="pdf") as document:
            actual = "".join(page.get_text() for page in document)
        assert "Исправленный текст" in actual
        assert "Строка 2" in actual
        assert "0шибка" not in actual
    else:
        document = document_from_dict(exported.json())
        assert "\n".join(b.plain_text for s in document.sections for b in s.blocks) == text


def test_concurrent_edits_and_stale_export(draft):
    client, url, _ = draft
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda text: client.put(url, json={"text": text, "revision": 1}), ["first", "second"]))
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r.json()["text"] for r in results if r.status_code == 200)
    assert client.get(url).json()["text"] == winner
    assert client.get(url + "/export?revision=1").status_code == 409


@pytest.mark.parametrize("payload", [{"revision": 1}, {"text": "x", "revision": 0},
                                     {"text": "\u0000", "revision": 1}, {"text": "x" * 1_000_001, "revision": 1}])
def test_invalid_edit_preserves_document(draft, payload):
    client, url, _ = draft
    assert client.put(url, json=payload).status_code == 422
    assert client.get(url).json()["text"] == "0шибка\n"


def test_empty_text_and_newline_normalization(draft):
    client, url, _ = draft
    assert client.put(url, json={"text": "a\r\nb\rc\n", "revision": 1}).json()["text"] == "a\nb\nc\n"
    assert client.put(url, json={"text": "", "revision": 2}).json()["text"] == ""
    assert client.get(url + "/export?revision=3").content == b""


def test_expiration_and_invalid_format(draft):
    client, url, store = draft
    assert client.get(url + "/export?revision=1&format=exe").status_code == 422
    store.ttl_seconds = -1
    assert client.get(url).status_code == 404
    assert client.put(url, json={"text": "revived", "revision": 1}).status_code == 404


def test_storage_failure_preserves_saved_version(draft, monkeypatch):
    client, url, _ = draft

    def fail(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(TaskStore, "set", fail)
    assert client.put(url, json={"text": "new", "revision": 1}).status_code == 503
    assert client.get(url).json()["text"] == "0шибка\n"
