import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from textalchemy import __version__
from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.core.database import Database
from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.inspection import DocumentInspection
from textalchemy.core.types import DocFormat
from textalchemy.web.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_task_store(monkeypatch, tmp_path_factory):
    """Фоновые задачи пишутся в отдельное временное хранилище, а не в user-data."""
    import importlib

    from textalchemy.web.tasks import TaskStore

    web_app = importlib.import_module("textalchemy.web.app")
    store = TaskStore(tmp_path_factory.mktemp("web-tasks"))
    monkeypatch.setattr(web_app, "tasks_store", store)
    from textalchemy.web.routes import convert as convert_route

    monkeypatch.setattr(convert_route, "tasks_store", store)


def _client_task_store():
    from textalchemy.web.routes import convert as convert_route

    return convert_route.tasks_store


def test_web_version_uses_package_metadata():
    assert app.version == __version__


def test_dashboard():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_extract_page():
    resp = client.get("/extract")
    assert resp.status_code == 200


def test_convert_page():
    resp = client.get("/convert")
    assert resp.status_code == 200
    assert "Максимально похожий вид" in resp.text
    assert "Скачать результат" in resp.text
    assert 'id="sourceInspection"' in resp.text
    assert 'id="comparisonSection"' in resp.text


def test_organize_page():
    resp = client.get("/pipeline")
    assert resp.status_code == 200


def test_bibliography_page():
    resp = client.get("/bibliography")
    assert resp.status_code == 200


def test_rename_page():
    resp = client.get("/matching")
    assert resp.status_code == 200


def test_matching_page():
    resp = client.get("/matching")
    assert resp.status_code == 200


def test_reports_page():
    resp = client.get("/reports")
    assert resp.status_code == 200


def test_export_page():
    resp = client.get("/export")
    assert resp.status_code == 200


def test_recognize_page():
    resp = client.get("/recognize")
    assert resp.status_code == 200


def test_generate_page():
    resp = client.get("/generate")
    assert resp.status_code == 200


def test_api_info():
    resp = client.get("/api/info")
    assert resp.status_code == 200
    data = resp.json()
    assert "name" in data
    assert "version" in data
    assert "modules" in data


def test_legacy_bibliography_migration_reports_invalid_json(monkeypatch, tmp_path, caplog):
    web_app = importlib.import_module("textalchemy.web.app")
    legacy = tmp_path / "bibliography.json"
    legacy.write_text("{broken", encoding="utf-8")
    database = Database(tmp_path / "migration.db")
    monkeypatch.setattr(web_app, "data_dir", tmp_path)
    monkeypatch.setattr(web_app, "db", database)

    with caplog.at_level("ERROR", logger="textalchemy.web.app"):
        web_app._migrate_json_to_db()

    assert legacy.exists()
    assert database.all_items() == []
    assert "Failed to migrate legacy bibliography" in caplog.text
    database.engine.dispose()


def test_legacy_bibliography_migration_is_successful(monkeypatch, tmp_path):
    web_app = importlib.import_module("textalchemy.web.app")
    legacy = tmp_path / "bibliography.json"
    legacy.write_text('[{"title": "Migrated"}]', encoding="utf-8")
    database = Database(tmp_path / "migration.db")
    monkeypatch.setattr(web_app, "data_dir", tmp_path)
    monkeypatch.setattr(web_app, "db", database)

    web_app._migrate_json_to_db()

    assert not legacy.exists()
    assert (tmp_path / "bibliography.json.imported").exists()
    assert [item.title for item in database.all_items()] == ["Migrated"]
    database.engine.dispose()


def test_api_bibliography():
    resp = client.get("/api/bibliography")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_add_bibliography():
    resp = client.post("/api/bibliography", data={
        "authors": "Ivanov I.I.",
        "title": "Test Article",
        "doc_type": "article",
        "year": "2024",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["item"]["title"] == "Test Article"


def test_api_config():
    resp = client.get("/api/config")
    assert resp.status_code == 200
    cfg = resp.json()
    assert "source_dir" in cfg


def test_api_stats():
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_bib" in data
    assert "total_files" in data


def test_api_export_json():
    resp = client.get("/api/export/json")
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]


def test_api_export_markdown():
    resp = client.get("/api/export/markdown")
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]


def test_api_export_gost():
    resp = client.get("/api/export/gost")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


def test_api_export_ris():
    resp = client.get("/api/export/ris")
    assert resp.status_code == 200


def test_api_export_csv():
    resp = client.get("/api/export/csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]


def test_api_export_bibtex():
    resp = client.get("/api/export/bibtex")
    assert resp.status_code == 200


def test_api_export_unknown():
    resp = client.get("/api/export/unknown")
    assert resp.status_code == 400


def test_api_templates():
    resp = client.get("/api/generate/templates")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Bibliography CRUD ──────────────────────────────

def test_api_bibliography_update():
    resp = client.put("/api/bibliography/1", data={
        "authors": "Updated Author",
        "title": "Updated Title",
        "doc_type": "article",
    })
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert resp.json()["success"] is True


def test_api_bibliography_update_not_found():
    resp = client.put("/api/bibliography/9999", data={
        "authors": "None",
        "title": "None",
        "doc_type": "article",
    })
    assert resp.status_code == 404


def test_api_bibliography_delete():
    resp = client.delete("/api/bibliography/1")
    assert resp.status_code == 200


# ── Matching ───────────────────────────────────────

def test_api_match_run():
    resp = client.post("/api/match/run", data={
        "source_dir": str(Path.cwd() / "tests"),
        "threshold": "0.30",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "matched" in data
    assert "unmatched" in data


def test_api_match_report():
    resp = client.get("/api/match/report")
    assert resp.status_code == 200
    data = resp.json()
    assert "matched" in data


# ── Config ─────────────────────────────────────────

def test_api_update_config():
    resp = client.post("/api/config", data={"cfg": '{"source_dir": "./docs"}'})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Convert ────────────────────────────────────────

def test_api_convert_no_file():
    resp = client.post("/api/convert")
    assert resp.status_code in (400, 422)


def test_api_convert_inspect_no_file():
    response = client.post("/api/convert/inspect")
    assert response.status_code in (400, 422)


def test_api_convert_status_not_found():
    resp = client.get("/api/convert/status/nonexistent")
    assert resp.status_code == 404


def test_api_convert_inspect_returns_public_structure_and_cleans_workspace(monkeypatch, tmp_path):
    def fake_inspect(path):
        return DocumentInspection(
            path,
            "pptx",
            metrics={"pages": 2, "paragraphs": 5, "tables": 1, "images": 2},
        )

    monkeypatch.setattr("textalchemy.web.routes.convert.inspect_path", fake_inspect)
    monkeypatch.setattr(
        "textalchemy.web.routes.convert.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path),
    )

    response = client.post(
        "/api/convert/inspect",
        files={"file": (r"..\deck.pptx", b"pptx", "application/octet-stream")},
    )

    assert response.status_code == 200
    inspection = response.json()["inspection"]
    assert inspection["source_path"] == "deck.pptx"
    assert inspection["source_format"] == "pptx"
    assert inspection["metrics"]["tables"] == 1
    assert list(tmp_path.iterdir()) == []


def test_api_convert_capabilities_are_runtime_plans(monkeypatch):
    monkeypatch.setattr("textalchemy.convert.executor.requirement_available", lambda _requirement: True)
    response = client.get("/api/convert/capabilities")
    assert response.status_code == 200
    sources = {source["format"]: source for source in response.json()["sources"]}
    assert {"pdf", "docx", "pptx", "model"} <= sources.keys()

    pdf_targets = {target["format"]: target for target in sources["pdf"]["targets"]}
    assert "docx" in pdf_targets
    assert "html" not in pdf_targets  # unsafe path-only intermediate routes are not advertised
    assert set(pdf_targets["docx"]["modes"]) == {"balanced", "faithful", "editable"}

    docx_targets = {target["format"]: target for target in sources["docx"]["targets"]}
    assert {"pdf", "html", "latex", "model"} <= docx_targets.keys()
    assert docx_targets["pdf"]["plans"]["faithful"]["steps"] == ["docx.model", "model.pdf"]


def test_api_convert_returns_report_and_separate_artifact(monkeypatch):
    captured = {}

    def fake_execute(_executor, request):
        captured["request"] = request
        request.output_path.write_bytes(b"converted-document")
        report = ConversionReport(request.output_path)
        report.metrics["executed_steps"] = ["pdf.docx.test"]
        return report

    monkeypatch.setattr("textalchemy.web.routes.convert.ConversionExecutor.execute", fake_execute)
    started = client.post(
        "/api/convert",
        files={"file": ("article.pdf", b"%PDF-test", "application/pdf")},
        data={"source_format": "pdf", "target_format": "docx", "mode": "editable"},
    )
    assert started.status_code == 200
    endpoints = started.json()

    status = client.get(endpoints["status"])
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "done"
    assert payload["report"]["success"] is True
    assert payload["report"]["metrics"]["executed_steps"] == ["pdf.docx.test"]
    assert "content" not in payload

    request = captured["request"]
    assert request.source is DocFormat.PDF
    assert request.target is DocFormat.DOCX
    assert request.mode is ConversionMode.EDITABLE

    result = client.get(endpoints["result"])
    assert result.status_code == 200
    assert result.content == b"converted-document"
    assert "article.docx" in result.headers["content-disposition"]


def test_api_convert_compares_source_and_result_structure(monkeypatch):
    def fake_execute(_executor, request):
        request.output_path.write_bytes(b"converted-pdf")
        return ConversionReport(request.output_path)

    def fake_inspect(path):
        is_source = path.suffix == ".docx"
        return DocumentInspection(
            path,
            path.suffix.removeprefix("."),
            metrics={
                "pages": 1,
                "paragraphs": 2,
                "characters": 100 if is_source else 80,
                "tables": 1 if is_source else 0,
            },
            pages=[
                {
                    "index": 0,
                    "width_pt": 595.28,
                    "height_pt": 841.89,
                    "margin_top_pt": 72,
                    "margin_right_pt": 72,
                    "margin_bottom_pt": 72,
                    "margin_left_pt": 72,
                }
            ],
        )

    monkeypatch.setattr("textalchemy.web.routes.convert.ConversionExecutor.execute", fake_execute)
    monkeypatch.setattr("textalchemy.web.routes.convert.inspect_path", fake_inspect)
    monkeypatch.setattr("textalchemy.convert.executor.requirement_available", lambda _requirement: True)
    response = client.post(
        "/api/convert",
        files={"file": ("source.docx", b"docx", "application/octet-stream")},
        data={"source_format": "docx", "target_format": "pdf"},
    )

    assert response.status_code == 200, response.text
    status = client.get(response.json()["status"]).json()
    assert status["source_inspection"]["source_path"] == "source.docx"
    assert status["target_inspection"]["source_path"] == "source.pdf"
    assert status["comparison"]["retention"]["characters"]["ratio"] == 0.8
    assert status["comparison"]["retention"]["tables"]["ratio"] == 0
    assert status["comparison"]["geometry_summary"]["max_dimension_error_pt"] == 0


def test_api_convert_rejects_unknown_mode():
    response = client.post(
        "/api/convert",
        files={"file": ("article.pdf", b"%PDF-test", "application/pdf")},
        data={"source_format": "pdf", "target_format": "docx", "mode": "impossible"},
    )
    assert response.status_code == 400


def test_api_convert_rejects_oversized_upload_and_cleans_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "textalchemy.web.routes.convert.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path, max_bytes=5),
    )

    response = client.post(
        "/api/convert",
        files={"file": ("article.pdf", b"123456", "application/pdf")},
        data={"source_format": "pdf", "target_format": "docx"},
    )

    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []


def test_api_convert_sanitizes_uploaded_path(monkeypatch, tmp_path):
    captured = {}

    def fake_execute(_executor, request):
        captured["source"] = request.input_path
        request.output_path.write_bytes(b"converted")
        return ConversionReport(request.output_path)

    monkeypatch.setattr("textalchemy.web.routes.convert.ConversionExecutor.execute", fake_execute)
    monkeypatch.setattr(
        "textalchemy.web.routes.convert.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path),
    )
    response = client.post(
        "/api/convert",
        files={"file": (r"..\..\article.pdf", b"%PDF-test", "application/pdf")},
        data={"source_format": "pdf", "target_format": "docx"},
    )

    assert response.status_code == 200
    assert captured["source"].name == "article.pdf"
    assert list(tmp_path.iterdir()) == []


def test_api_convert_legacy_format_remains_supported(monkeypatch):
    def fake_execute(_executor, request):
        request.output_path.write_bytes(b"legacy-result")
        return ConversionReport(request.output_path)

    monkeypatch.setattr("textalchemy.web.routes.convert.ConversionExecutor.execute", fake_execute)
    response = client.post(
        "/api/convert",
        files={"file": ("article.pdf", b"%PDF-test", "application/pdf")},
        data={"fmt": "pdf"},
    )
    assert response.status_code == 200
    assert client.get(response.json()["status"]).json()["status"] == "done"


def test_api_convert_serves_single_file_html(monkeypatch):
    def fake_execute(_executor, request):
        request.output_path.write_text("<html>converted</html>", encoding="utf-8")
        return ConversionReport(request.output_path)

    monkeypatch.setattr("textalchemy.web.routes.convert.ConversionExecutor.execute", fake_execute)
    response = client.post(
        "/api/convert",
        files={"file": ("article.docx", b"docx-test", "application/octet-stream")},
        data={"source_format": "docx", "target_format": "html", "mode": "balanced"},
    )
    endpoints = response.json()
    result = client.get(endpoints["result"])
    assert result.status_code == 200
    assert result.headers["content-type"].startswith("text/html")
    assert result.content == b"<html>converted</html>"


# ── Convert: visual preview ──────────────────────────

def _seed_preview_task(store, task_id="preview-task"):
    task_dir = store.root / task_id
    source_dir = task_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "in.pdf").write_bytes(b"%PDF-1.4 preview source")
    (task_dir / "out.pdf").write_bytes(b"%PDF-1.4 preview result")
    store.set(task_id, {"status": "done", "artifact": "out.pdf", "filename": "out.pdf"})
    return task_id


def test_api_convert_single_preserves_source_for_preview(monkeypatch):
    from textalchemy.web.routes import convert as convert_route

    def fake_execute(_executor, request):
        request.output_path.write_bytes(b"converted-document")
        return ConversionReport(request.output_path)

    monkeypatch.setattr("textalchemy.web.routes.convert.ConversionExecutor.execute", fake_execute)
    response = client.post(
        "/api/convert",
        files={"file": ("article.pdf", b"%PDF-test", "application/pdf")},
        data={"source_format": "pdf", "target_format": "docx"},
    )
    assert response.status_code == 200
    assert convert_route.tasks_store.source_path(response.json()["task_id"]) is not None


def test_api_convert_preview_meta_and_page(monkeypatch):
    store = _client_task_store()
    task_id = _seed_preview_task(store)

    def fake_count(_preview_dir, _file, _side):
        return 3

    def fake_png(_preview_dir, _file, _side, page_index, dpi=110):
        return b"\x89PNG\r\n\x1a\npreview-page"

    monkeypatch.setattr("textalchemy.web.routes.convert.cached_page_count", fake_count)
    monkeypatch.setattr("textalchemy.web.routes.convert.cached_page_png", fake_png)

    meta = client.get(f"/api/convert/preview/{task_id}/meta")
    assert meta.status_code == 200
    body = meta.json()
    assert body["source"]["available"] is True
    assert body["source"]["pages"] == 3
    assert body["target"]["pages"] == 3
    assert body["target"]["error"] is None

    page = client.get(f"/api/convert/preview/{task_id}?side=target&page=2")
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/png"
    assert page.content == b"\x89PNG\r\n\x1a\npreview-page"
    assert "max-age" in page.headers.get("cache-control", "")

    assert client.get(f"/api/convert/preview/{task_id}?side=target&page=9").status_code == 404
    assert client.get(f"/api/convert/preview/{task_id}?side=other").status_code == 400
    assert client.get(f"/api/convert/preview/{task_id}?side=target&page=0").status_code == 400
    assert client.get("/api/convert/preview/nonexistent/meta").status_code == 404


def test_api_convert_preview_requires_done_task(monkeypatch):
    store = _client_task_store()
    task_id = "pending-preview"
    store.set(task_id, {"status": "running"})

    meta = client.get(f"/api/convert/preview/{task_id}/meta")
    assert meta.status_code == 409
    page = client.get(f"/api/convert/preview/{task_id}?side=source")
    assert page.status_code == 409


def test_api_convert_preview_target_unavailable_for_directory_artifacts(monkeypatch):
    store = _client_task_store()
    task_id = "dir-artifact"
    task_dir = store.root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    source_dir = task_dir / "source"
    source_dir.mkdir(exist_ok=True)
    (source_dir / "in.pdf").write_bytes(b"%PDF")
    (task_dir / "deck-html.zip").write_bytes(b"zip")
    store.set(task_id, {"status": "done", "artifact": "deck-html.zip", "filename": "deck-html.zip"})

    def fake_count(_preview_dir, file, _side):
        return 3 if file.suffix == ".pdf" else 0

    monkeypatch.setattr("textalchemy.web.routes.convert.cached_page_count", fake_count)

    meta = client.get(f"/api/convert/preview/{task_id}/meta").json()
    assert meta["source"]["available"] is True
    assert meta["source"]["pages"] == 3
    assert meta["target"]["available"] is False
    assert meta["target"]["pages"] == 0


# ── Convert: batch queue + history ──────────────────

def _batch_files():
    return [
        ("files", ("a.pdf", b"%PDF-a", "application/pdf")),
        ("files", ("b.pdf", b"%PDF-b", "application/pdf")),
    ]


def test_api_convert_batch_runs_each_file_and_cleans(monkeypatch, tmp_path):
    def fake_execute(_executor, request):
        request.output_path.write_bytes(b"converted-" + request.input_path.name.encode())
        return ConversionReport(request.output_path)

    monkeypatch.setattr("textalchemy.web.routes.convert.ConversionExecutor.execute", fake_execute)
    monkeypatch.setattr(
        "textalchemy.web.routes.convert.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path),
    )
    response = client.post("/api/convert/batch", files=_batch_files(), data={"target_format": "docx"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert len(body["tasks"]) == 2
    assert {task["name"] for task in body["tasks"]} == {"a.pdf", "b.pdf"}
    assert {task["source_format"] for task in body["tasks"]} == {"pdf"}

    job = client.get(f"/api/convert/jobs/{body['job_id']}").json()
    assert [task["status"] for task in job["tasks"]] == ["done", "done"]
    for task in job["tasks"]:
        result = client.get(task["result_url"])
        assert result.status_code == 200
        assert result.content == b"converted-" + task["name"].encode()
    assert list(tmp_path.iterdir()) == []


def test_api_convert_batch_requires_files():
    response = client.post("/api/convert/batch", data={"target_format": "docx"})
    assert response.status_code in (400, 422)


def test_api_convert_batch_limits_file_count():
    files = [("files", (f"file{i}.pdf", b"%PDF", "application/pdf")) for i in range(21)]
    response = client.post("/api/convert/batch", files=files)
    assert response.status_code == 400
    assert "максимум" in response.json()["detail"]


def test_api_convert_batch_rejects_unavailable_target_and_cleans(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "textalchemy.web.routes.convert.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path),
    )
    response = client.post("/api/convert/batch", files=_batch_files(), data={"target_format": "pptx"})
    assert response.status_code == 400
    assert "недоступен" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []


def test_api_convert_batch_rejects_unknown_mode():
    response = client.post("/api/convert/batch", files=_batch_files(), data={"mode": "impossible"})
    assert response.status_code == 400


def test_api_convert_jobs_lists_history(monkeypatch):
    def fake_execute(_executor, request):
        request.output_path.write_bytes(b"converted")
        return ConversionReport(request.output_path)

    monkeypatch.setattr("textalchemy.web.routes.convert.ConversionExecutor.execute", fake_execute)
    created = client.post("/api/convert/batch", files=_batch_files()).json()

    history = client.get("/api/convert/jobs").json()
    assert history["jobs"]
    latest = history["jobs"][0]
    assert latest["job_id"] == created["job_id"]
    assert latest["counts"]["done"] == 2
    assert latest["files"] == ["a.pdf", "b.pdf"]


def test_api_convert_job_not_found():
    assert client.get("/api/convert/jobs/nope").status_code == 404
    assert client.delete("/api/convert/jobs/nope").status_code == 404
    assert client.post("/api/convert/jobs/nope/rerun").status_code == 404


def test_api_convert_job_delete_removes_tasks(monkeypatch):
    def fake_execute(_executor, request):
        request.output_path.write_bytes(b"converted")
        return ConversionReport(request.output_path)

    monkeypatch.setattr("textalchemy.web.routes.convert.ConversionExecutor.execute", fake_execute)
    created = client.post("/api/convert/batch", files=_batch_files()).json()

    response = client.delete(f"/api/convert/jobs/{created['job_id']}")
    assert response.status_code == 200
    assert client.get(f"/api/convert/jobs/{created['job_id']}").status_code == 404
    for task in created["tasks"]:
        assert client.get(task["status"]).status_code == 404


def test_api_convert_job_rerun_uses_stored_sources(monkeypatch):
    calls = []

    def fake_execute(_executor, request):
        calls.append(request.input_path.name)
        request.output_path.write_bytes(b"converted")
        return ConversionReport(request.output_path)

    monkeypatch.setattr("textalchemy.web.routes.convert.ConversionExecutor.execute", fake_execute)
    created = client.post("/api/convert/batch", files=_batch_files()).json()
    assert len(calls) == 2

    rerun = client.post(f"/api/convert/jobs/{created['job_id']}/rerun")
    assert rerun.status_code == 200
    assert len(rerun.json()["launched"]) == 2
    assert len(calls) == 4

    job = client.get(f"/api/convert/jobs/{created['job_id']}").json()
    assert [task["status"] for task in job["tasks"]] == ["done", "done"]


# ── Import ─────────────────────────────────────────

def test_api_import_no_file():
    resp = client.post("/api/bibliography/import")
    assert resp.status_code in (400, 422)


# ── Preview rename ─────────────────────────────────

def test_api_preview_rename():
    resp = client.post("/api/preview/rename", data={
        "source_dir": str(Path.cwd() / "tests"),
    })
    assert resp.status_code == 200


# ── Extract ────────────────────────────────────────

def test_api_extract_text_no_file():
    resp = client.post("/api/extract/text")
    assert resp.status_code in (400, 422)


def test_api_extract_latex_no_file():
    resp = client.post("/api/extract/latex")
    assert resp.status_code in (400, 422)


# ── Recognize ──────────────────────────────────────

def test_api_recognize_no_file():
    resp = client.post("/api/recognize")
    assert resp.status_code in (400, 422)


# ── Generate ───────────────────────────────────────

def test_api_generate_no_data():
    resp = client.post("/api/generate")
    assert resp.status_code in (400, 422)


# ── 404 handler ────────────────────────────────────

def test_404():
    resp = client.get("/nonexistent-route")
    assert resp.status_code == 404


# ── Extract: текст и LaTeX ─────────────────────────

def test_api_extract_text_returns_plain(tmp_path, monkeypatch):
    from textalchemy.core.artifacts import ArtifactWorkspace

    monkeypatch.setattr(
        "textalchemy.web.routes.extract.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path),
    )
    resp = client.post(
        "/api/extract/text",
        files={"file": ("notes.txt", "Привет из файла".encode("utf-8"), "text/plain")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "Привет из файла" in body["text"]
    assert list(tmp_path.iterdir()) == []


def test_api_extract_text_error(tmp_path, monkeypatch):
    from textalchemy.core.artifacts import ArtifactWorkspace

    monkeypatch.setattr(
        "textalchemy.web.routes.extract.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path),
    )

    def boom(**kwargs):
        raise RuntimeError("reader exploded")

    monkeypatch.setattr("textalchemy.web.routes.extract.extract_text", boom)
    resp = client.post(
        "/api/extract/text",
        files={"file": ("notes.txt", b"x", "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert "reader exploded" in resp.json()["error"]


def test_api_extract_latex_returns_tex(tmp_path, monkeypatch):
    from textalchemy.core.artifacts import ArtifactWorkspace

    monkeypatch.setattr(
        "textalchemy.web.routes.extract.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path),
    )

    def fake_latex(src, out, doc_type="manuscript"):
        Path(out).write_text("\\section{Раздел}", encoding="utf-8")

    monkeypatch.setattr("textalchemy.web.routes.extract.docx_to_latex", fake_latex)
    resp = client.post(
        "/api/extract/latex",
        files={"file": ("doc.docx", b"docx-bytes", "application/octet-stream")},
    )
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "\\section{Раздел}" in resp.text
    assert list(tmp_path.iterdir()) == []


def test_api_extract_latex_error(tmp_path, monkeypatch):
    from textalchemy.core.artifacts import ArtifactWorkspace

    monkeypatch.setattr(
        "textalchemy.web.routes.extract.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path),
    )

    def boom(src, out, doc_type="manuscript"):
        raise RuntimeError("latex failed")

    monkeypatch.setattr("textalchemy.web.routes.extract.docx_to_latex", boom)
    resp = client.post(
        "/api/extract/latex",
        files={"file": ("doc.docx", b"docx-bytes", "application/octet-stream")},
    )
    assert resp.json()["success"] is False
    assert "latex failed" in resp.json()["error"]


# ── Recognize: OCR ─────────────────────────────────

def test_api_recognize_success(tmp_path, monkeypatch):
    from textalchemy.core.artifacts import ArtifactWorkspace

    monkeypatch.setattr(
        "textalchemy.web.routes.recognize.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path),
    )

    class FakeEngine:
        is_available = True

        def __init__(self, languages, use_gpu=False):
            self.languages = languages

        @property
        def backend_name(self):
            return "tesseract"

        def recognize(self, path, handwriting=False):
            return type("R", (), {"text": "распознано", "confidence": 0.9})()

    monkeypatch.setattr("textalchemy.web.routes.recognize.OcrEngine", FakeEngine)
    resp = client.post(
        "/api/recognize",
        files={"file": ("page.png", b"png-bytes", "image/png")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["text"] == "распознано"
    assert body["backend"] == "tesseract"
    assert list(tmp_path.iterdir()) == []


def test_api_recognize_stub_when_backend_unavailable(tmp_path, monkeypatch):
    from textalchemy.core.artifacts import ArtifactWorkspace

    monkeypatch.setattr(
        "textalchemy.web.routes.recognize.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path),
    )

    class FakeEngine:
        is_available = False

        def __init__(self, languages, use_gpu=False):
            pass

        @property
        def backend_name(self):
            return None

        def recognize(self, path, handwriting=False):
            raise AssertionError("не должен вызываться")

    monkeypatch.setattr("textalchemy.web.routes.recognize.OcrEngine", FakeEngine)
    resp = client.post(
        "/api/recognize",
        files={"file": ("page.png", b"png-bytes", "image/png")},
    )
    body = resp.json()
    assert body["success"] is True
    assert "[STUB]" in body["text"]
    assert body["backend"] is None


def test_api_recognize_error(tmp_path, monkeypatch):
    from textalchemy.core.artifacts import ArtifactWorkspace

    monkeypatch.setattr(
        "textalchemy.web.routes.recognize.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path),
    )

    class FakeEngine:
        is_available = True

        def __init__(self, languages, use_gpu=False):
            pass

        @property
        def backend_name(self):
            return "easyocr"

        def recognize(self, path, handwriting=False):
            raise RuntimeError("ocr backend crashed")

    monkeypatch.setattr("textalchemy.web.routes.recognize.OcrEngine", FakeEngine)
    resp = client.post(
        "/api/recognize",
        files={"file": ("page.png", b"png-bytes", "image/png")},
    )
    assert resp.json()["success"] is False
    assert "ocr backend crashed" in resp.json()["error"]


# ── Generate: шаблоны ──────────────────────────────

def test_api_generate_lists_templates(monkeypatch):
    from textalchemy.generate.template import DocumentTemplate

    monkeypatch.setattr(
        "textalchemy.web.routes.generate.list_templates",
        lambda: [DocumentTemplate(name="report", description="Отчёт")],
    )
    resp = client.get("/api/generate/templates")
    assert resp.status_code == 200
    assert resp.json() == [{"name": "report", "description": "Отчёт"}]


def test_api_generate_rejects_bad_json():
    resp = client.post(
        "/api/generate",
        data={"template": "report", "params": "{not json"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "JSON" in body["error"]


def test_api_generate_returns_file(tmp_path, monkeypatch):
    from textalchemy.core.artifacts import ArtifactWorkspace

    monkeypatch.setattr(
        "textalchemy.web.routes.generate.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path),
    )

    def fake_generate(template_name, output_path, params):
        Path(output_path).write_bytes(b"docx-content")
        return output_path

    monkeypatch.setattr("textalchemy.web.routes.generate.generate_document", fake_generate)
    resp = client.post(
        "/api/generate",
        data={"template": "report", "output": "out.docx", "params": '{"a": 1}'},
    )
    assert resp.status_code == 200
    assert "out.docx" in resp.headers["content-disposition"]
    assert resp.content == b"docx-content"


def test_api_generate_error(tmp_path, monkeypatch):
    from textalchemy.core.artifacts import ArtifactWorkspace

    monkeypatch.setattr(
        "textalchemy.web.routes.generate.create_web_workspace",
        lambda: ArtifactWorkspace(parent=tmp_path),
    )

    def boom(template_name, output_path, params):
        raise RuntimeError("generation failed")

    monkeypatch.setattr("textalchemy.web.routes.generate.generate_document", boom)
    resp = client.post(
        "/api/generate",
        data={"template": "report", "params": "{}"},
    )
    assert resp.json()["success"] is False
    assert "generation failed" in resp.json()["error"]
