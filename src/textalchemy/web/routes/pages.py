"""Thin presentation routes for server-rendered pages."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from textalchemy.web.app import _load_bib, _load_config, _matching_path, app, templates
from textalchemy.web.services.page_context import PageContextService


def _context() -> PageContextService:
    return PageContextService(
        load_bibliography=_load_bib,
        load_config=_load_config,
        matching_path=_matching_path,
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "index.html", _context().dashboard())


@app.get("/extract", response_class=HTMLResponse)
async def extract_page(request: Request):
    return templates.TemplateResponse(request, "extract.html")


@app.get("/convert", response_class=HTMLResponse)
async def convert_page(request: Request):
    return templates.TemplateResponse(request, "convert.html")


@app.get("/pipeline", response_class=HTMLResponse)
async def pipeline_page(request: Request):
    return templates.TemplateResponse(request, "pipeline.html")


@app.get("/bibliography", response_class=HTMLResponse)
async def bibliography_page(request: Request):
    return templates.TemplateResponse(request, "bibliography.html", _context().bibliography())


@app.get("/matching", response_class=HTMLResponse)
async def matching_page(request: Request):
    return templates.TemplateResponse(request, "matching.html", _context().matching())


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    return templates.TemplateResponse(request, "reports.html", _context().reports())


@app.get("/recognize", response_class=HTMLResponse)
async def recognize_page(request: Request):
    return templates.TemplateResponse(request, "recognize.html")


@app.get("/generate", response_class=HTMLResponse)
async def generate_page(request: Request):
    return templates.TemplateResponse(request, "generate.html")


@app.get("/export", response_class=HTMLResponse)
async def export_page(request: Request):
    return templates.TemplateResponse(request, "export.html")
