from pathlib import Path

from fastapi.testclient import TestClient

from textalchemy.web.main import app

client = TestClient(app)


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


def test_api_convert_status_not_found():
    resp = client.get("/api/convert/status/nonexistent")
    assert resp.status_code == 404


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
