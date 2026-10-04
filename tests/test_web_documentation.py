"""Встроенная документация доступна без отдельного сервера и файлов пользователя."""

from __future__ import annotations

import importlib
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from textalchemy.web.main import app
from textalchemy.web.services.documentation import DocumentationService
from tools.documentation import bundle


def test_bundle_is_deterministic_and_rejects_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>Руководство</h1>", encoding="utf-8")
    target = tmp_path / "documentation.zip"
    monkeypatch.setattr(bundle, "SITE", site)
    monkeypatch.setattr(bundle, "BUNDLE", target)
    assert bundle.sync_bundle()
    original = target.read_bytes()
    assert bundle.site_archive(site) == original
    assert not bundle.sync_bundle(check=True)
    (site / "index.html").write_text("<h1>Обновлено</h1>", encoding="utf-8")
    with pytest.raises(ValueError, match="устарел"):
        bundle.sync_bundle(check=True)
    assert target.read_bytes() == original


@pytest.mark.parametrize("path", ["../library.db", "/private", "doc/../../private", r"..\private", "\x00"])
def test_documentation_rejects_paths_outside_bundle(tmp_path: Path, path: str) -> None:
    with pytest.raises(LookupError):
        DocumentationService(tmp_path / "unused.zip").read(path)


def test_service_returns_only_bundled_pages(tmp_path: Path) -> None:
    target = tmp_path / "docs.zip"
    with ZipFile(target, "w") as archive:
        archive.writestr("index.html", "<h1>Guide</h1>")
        archive.writestr("chapter/index.html", "<h1>Chapter</h1>")
        archive.writestr("assets/style.css", "body {color:purple}")
    service = DocumentationService(target)
    assert service.read("").content == b"<h1>Guide</h1>"
    assert service.read("chapter").directory
    assert not service.read("chapter/").directory
    assert service.read("assets/style.css").media_type == "text/css"
    with pytest.raises(LookupError):
        service.read("library.db")


def test_actual_help_site_guide_search_assets_and_source_links() -> None:
    with TestClient(app) as client:
        assert client.get("/help", follow_redirects=False).headers["location"] == "/help/"
        home = client.get("/help/")
        assert home.status_code == 200 and "TextAlchemy" in home.text
        assert "text/html" in home.headers["content-type"]
        assert client.get("/help/doc/guide/", follow_redirects=False).status_code == 200
        assert client.get("/help/doc/guide", follow_redirects=False).headers["location"] == "/help/doc/guide/"
        assert client.get("/help/doc/assets/documentation.css").headers["content-type"].startswith("text/css")
        assert client.get("/help/search/search_index.json").json()["docs"]
        assert client.get("/help/doc/reference/code/").status_code == 200
        assert client.get("/help/files/src/textalchemy/web/routes/extract.py.html").status_code == 200
        assert client.get("/help/nonexistent").status_code == 404


def test_previous_help_bookmarks_redirect_only_to_existing_safe_pages() -> None:
    with TestClient(app) as client:
        result = client.get("/help/docs/guide/", follow_redirects=False)
        assert result.status_code == 308
        assert result.headers["location"] == "/help/doc/guide/"
        assert client.get("/help/docs/missing/", follow_redirects=False).status_code == 404
        assert client.get("/help/docs/%2E%2E/private", follow_redirects=False).status_code == 404


def test_missing_bundle_has_readable_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    route = importlib.import_module("textalchemy.web.routes.documentation")
    monkeypatch.setattr(route, "DocumentationService", lambda: DocumentationService(tmp_path / "missing.zip"))
    with TestClient(app) as client:
        result = client.get("/help/")
        assert result.status_code == 503 and "документацию" in result.json()["detail"]


def test_latex_download_accepts_unicode_filename(monkeypatch: pytest.MonkeyPatch) -> None:
    def latex(source: Path, output: Path, doc_type: str) -> None:
        output.write_text("Проверка", encoding="utf-8")

    monkeypatch.setattr("textalchemy.web.routes.extract.docx_to_latex", latex)
    with TestClient(app) as client:
        result = client.post("/api/extract/latex", files={"file": ("Учебная работа.docx", b"input")})
    assert result.status_code == 200 and result.text == "Проверка"
    assert "filename*=UTF-8''" + quote("Учебная работа.tex") in result.headers["content-disposition"]
