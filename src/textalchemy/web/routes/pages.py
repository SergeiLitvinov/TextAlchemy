"""HTML-страницы дашборда (рендерятся через Jinja2)."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from textalchemy.web.app import _load_bib, _load_config, _matching_path, app, templates


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    bib = _load_bib()
    report_path = _matching_path()
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else None
    if report is not None:
        import json

        report = json.loads(report)
    return templates.TemplateResponse(request, "index.html", {
        "bib_count": len(bib),
        "report": report,
    })


@app.get("/extract", response_class=HTMLResponse)
async def extract_page(request: Request):
    return templates.TemplateResponse(request, "extract.html")


@app.get("/convert", response_class=HTMLResponse)
async def convert_page(request: Request):
    return templates.TemplateResponse(request, "convert.html")


@app.get("/pipeline", response_class=HTMLResponse)
async def pipeline_page(request: Request):
    return templates.TemplateResponse(request, "organize.html")


@app.get("/bibliography", response_class=HTMLResponse)
async def bibliography_page(request: Request):
    bib = _load_bib()
    return templates.TemplateResponse(request, "bibliography.html", {"bib_items": bib})


@app.get("/matching", response_class=HTMLResponse)
async def matching_page(request: Request):
    bib = _load_bib()
    cfg = _load_config()
    src_dir = cfg.get("source_dir", "./literature_files")
    from pathlib import Path

    files = sorted(
        f.name for f in Path(src_dir).rglob("*") if f.is_file() and f.suffix.lower() in {".pdf", ".docx", ".djvu", ".txt"}
    ) if Path(src_dir).exists() else []
    return templates.TemplateResponse(request, "matching.html", {
        "bib_items": bib,
        "config": cfg,
        "files": files,
    })


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    bib = _load_bib()
    cfg = _load_config()
    report_path = _matching_path()
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else None
    if report is not None:
        import json

        report = json.loads(report)
    return templates.TemplateResponse(request, "reports.html", {
        "bib_items": bib,
        "config": cfg,
        "report": report,
    })


@app.get("/recognize", response_class=HTMLResponse)
async def recognize_page(request: Request):
    return templates.TemplateResponse(request, "recognize.html")


@app.get("/generate", response_class=HTMLResponse)
async def generate_page(request: Request):
    return templates.TemplateResponse(request, "generate.html")


@app.get("/export", response_class=HTMLResponse)
async def export_page(request: Request):
    return templates.TemplateResponse(request, "export.html")
