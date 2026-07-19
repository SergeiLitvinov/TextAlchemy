"""API запуска pipeline и экспорта."""
from __future__ import annotations

import json

import yaml
from fastapi import Form, HTTPException
from fastapi.responses import Response

from textalchemy.pipeline.render import render_bibtex, render_gost, render_json, render_markdown
from textalchemy.pipeline.runner import run_pipeline
from textalchemy.web.app import app, db


@app.post("/api/pipeline/run")
async def api_pipeline_run(spec: str = Form(...)):
    try:
        pipeline_def = json.loads(spec)
    except json.JSONDecodeError:
        pipeline_def = yaml.safe_load(spec)
    result = run_pipeline(pipeline_def)
    return {"success": True, "result": result.to_dict()}


@app.get("/api/export/{fmt}")
async def api_export(fmt: str):
    items = db.all_items()
    if fmt == "json":
        content = render_json(items=items)
        media_type = "application/json"
        filename = "bibliography.json"
    elif fmt == "markdown":
        content = render_markdown(items=items)
        media_type = "text/markdown"
        filename = "bibliography.md"
    elif fmt == "gost":
        content = render_gost(items=items)
        media_type = "text/plain; charset=utf-8"
        filename = "bibliography_gost.txt"
    elif fmt == "bibtex":
        content = render_bibtex(items=items)
        media_type = "application/x-bibtex"
        filename = "bibliography.bib"
    elif fmt == "ris":
        lines = []
        for it in items:
            au = it.authors if hasattr(it, "authors") else []
            title = it.title if hasattr(it, "title") else ""
            year = str(it.year) if hasattr(it, "year") and it.year else ""
            dt = it.doc_type if hasattr(it, "doc_type") else "GEN"
            for a in au:
                lines.append(f"AU  - {a}")
            lines.append(f"TI  - {title}")
            lines.append(f"PY  - {year}")
            lines.append(f"TY  - {dt.upper()[:4]}")
            lines.append("ER  -")
            lines.append("")
        content = "\n".join(lines)
        media_type = "application/x-research-info-systems"
        filename = "bibliography.ris"
    elif fmt == "csv":
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "authors", "title", "year", "doc_type", "source"])
        for it in items:
            w.writerow([
                getattr(it, "index", ""),
                "; ".join(getattr(it, "authors", [])),
                getattr(it, "title", ""),
                getattr(it, "year", ""),
                getattr(it, "doc_type", ""),
                getattr(it, "source", ""),
            ])
        content = buf.getvalue()
        media_type = "text/csv"
        filename = "bibliography.csv"
    else:
        raise HTTPException(status_code=400, detail="Unsupported format")
    return Response(content=content, media_type=media_type,
                    headers={"Content-Disposition": f"attachment; filename={filename}"})
