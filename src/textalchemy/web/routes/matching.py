"""API матчинга, превью переименования, статистики и конфигурации."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import Form

from textalchemy.pipeline.bibliography import parse_bibliography
from textalchemy.pipeline.match_files import match_files
from textalchemy.pipeline.name import name_from_match
from textalchemy.web.app import (
    _ensure_data,
    _load_bib,
    _load_config,
    _matching_path,
    _save_config,
    app,
    db,
)


@app.post("/api/match/run")
async def api_run_matching(
    source_dir: str = Form("./literature_files"),
    output_dir: str = Form("./renamed"),
    threshold: float = Form(0.30),
    bibliography_file: str = Form(""),
    dry_run: bool = Form(False),
):
    if bibliography_file:
        items = parse_bibliography(path=bibliography_file)
    else:
        items = db.all_items()

    matches = match_files(
        source=source_dir,
        items=items,
        threshold=threshold,
        output_dir=output_dir if not dry_run else None,
        copy=not dry_run,
    )

    results: dict = {"matched": [], "unmatched": [], "errors": [], "total": len(matches)}
    for m in matches:
        entry = {"file": m.document.path.name}
        if m.matched and m.item is not None:
            new_name = name_from_match(match=m, ext=m.document.path.suffix.lower()) or m.document.path.name
            results["matched"].append(
                {
                    "original": m.document.path.name,
                    "new": new_name,
                    "score": round(m.score, 2) if m.score else 0,
                }
            )
        else:
            results["unmatched"].append(entry)

    _ensure_data()
    from textalchemy.core.io import atomic_write_text

    atomic_write_text(_matching_path(), json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    cfg = _load_config()
    cfg["source_dir"] = source_dir
    cfg["output_dir"] = output_dir
    cfg["threshold"] = threshold
    if bibliography_file:
        cfg["bibliography_file"] = bibliography_file
    _save_config(cfg)

    return {"success": True, **results}


@app.get("/api/match/report")
async def api_get_matching_report():
    p = _matching_path()
    if not p.exists():
        return {"matched": [], "unmatched": [], "errors": [], "total": 0}
    return json.loads(p.read_text(encoding="utf-8"))


@app.post("/api/preview/rename")
async def api_preview_rename(
    source_dir: str = Form("./literature_files"),
    threshold: float = Form(0.30),
    bibliography_file: str = Form(""),
):
    if bibliography_file:
        items = parse_bibliography(path=bibliography_file)
    else:
        items = db.all_items()

    matches = match_files(
        source=source_dir,
        items=items,
        threshold=threshold,
        output_dir=None,
        copy=False,
    )

    preview = []
    for m in matches:
        if m.matched and m.item is not None:
            new_name = name_from_match(match=m, ext=m.document.path.suffix.lower()) or m.document.path.name
            preview.append(
                {
                    "original": m.document.path.name,
                    "new": new_name,
                    "match": True,
                    "score": round(m.score, 2) if m.score else 0,
                }
            )
        else:
            preview.append(
                {
                    "original": m.document.path.name,
                    "new": m.document.path.name,
                    "match": False,
                    "score": 0,
                }
            )

    return {"preview": preview, "total": len(preview), "matched": sum(1 for p in preview if p["match"])}


@app.get("/api/stats")
async def api_stats():
    bib = _load_bib()
    cfg = _load_config()
    src = Path(cfg.get("source_dir", "./literature_files"))
    out = Path(cfg.get("output_dir", "./renamed"))
    total_files = len([f for f in src.rglob("*") if f.is_file()]) if src.exists() else 0
    matched_files = len([f for f in out.rglob("*") if f.is_file()]) if out.exists() else 0
    doc_types: dict = {}
    for item in bib:
        dt = item.get("doc_type", "unknown")
        doc_types[dt] = doc_types.get(dt, 0) + 1
    report_path = _matching_path()
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else None
    if report is not None:
        report = json.loads(report)
    return {
        "total_bib": len(bib),
        "total_files": total_files,
        "matched_files": matched_files,
        "unmatched": total_files - matched_files,
        "progress": round(matched_files / len(bib) * 100, 1) if bib else 0,
        "doc_types": doc_types,
        "matching": report,
    }


@app.get("/api/config")
async def api_get_config():
    return _load_config()


@app.post("/api/config")
async def api_update_config(cfg: str = Form(...)):
    _save_config(json.loads(cfg))
    return {"success": True}
