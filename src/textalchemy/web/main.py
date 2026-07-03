import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

from textalchemy.core.database import Database
from textalchemy.organize.bibliography import BibItem

app = FastAPI(
    title="TextAlchemy",
    description="Универсальный инструментарий обработки научно-учебных документов.\n\n"
    "Модули: extract (DOCX→текст/LaTeX), convert (PDF→DOCX), organize (библиография + ренейм + ГОСТ), "
    "recognize (OCR), generate (шаблоны).\n\n"
    "Все API-эндпоинты доступны под /api/. Веб-интерфейс — статические HTML-страницы.",
    version=__import__("textalchemy").__version__,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

templates_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"
data_dir = Path.cwd() / ".textalchemy"

env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True, cache_size=0)
templates = Jinja2Templates(env=env)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Database
db = Database(db_path=data_dir / "library.db")


# ── helpers ──────────────────────────────────────────────────────────────────
def _safe_path(user_path: str) -> Path:
    p = Path(user_path)
    if ".." in p.parts:
        p = Path.cwd() / p
        p = p.resolve()
    return p.resolve()


def _bibitem_to_dict(item: BibItem) -> dict[str, Any]:
    return {
        "id": item.index,
        "authors": item.authors,
        "title": item.title,
        "doc_type": item.doc_type,
        "year": str(item.year) if item.year is not None else "",
        "journal": item.journal,
        "publisher": item.publisher,
        "city": item.city,
        "pages": item.pages,
        "isbn": item.isbn,
        "doi": item.doi,
        "source": item.source,
    }


def _dict_to_bibitem(d: dict, item_id: int | None = None) -> BibItem:
    year_raw = d.get("year", "")
    year = int(year_raw) if year_raw and str(year_raw).strip().isdigit() else None
    raw_id = d.get("id")
    index = item_id if item_id is not None else (int(raw_id) if raw_id is not None else 0)
    return BibItem(index=index,
        authors=d.get("authors", []),
        title=d.get("title", ""),
        year=year,
        doc_type=d.get("doc_type", "unknown"),
        source=d.get("source", ""),
        pages=d.get("pages", ""),
        doi=d.get("doi", ""),
        isbn=d.get("isbn", ""),
        url=d.get("url", ""),
        journal=d.get("journal", ""),
        publisher=d.get("publisher", ""),
        city=d.get("city", ""),
    )


def _ensure_data():
    data_dir.mkdir(parents=True, exist_ok=True)


def _migrate_json_to_db():
    """Import JSON file to DB on first run, then remove JSON."""
    p = data_dir / "bibliography.json"
    if not p.exists() or db.all_items():
        return
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        for d in raw:
            item = _dict_to_bibitem(d)
            db.add_item(item)
        p.rename(data_dir / "bibliography.json.imported")
    except Exception:
        pass


def _load_bib() -> list[dict[str, Any]]:
    _ensure_data()
    _migrate_json_to_db()
    items = db.all_items()
    return [_bibitem_to_dict(item) for item in items]


def _save_bib(items: list[dict[str, Any]]):
    _ensure_data()
    existing = {item.index for item in db.all_items()}
    new_ids = set()
    for i, d in enumerate(items):
        item_id = d.get("id")
        if item_id and item_id in existing:
            db.update_item(item_id, _dict_to_bibitem(d, item_id))
            new_ids.add(item_id)
        else:
            item = _dict_to_bibitem(d)
            added = db.add_item(item)
            items[i]["id"] = added.index
            new_ids.add(added.index)
    for old_id in existing - new_ids:
        db.delete_item(old_id)


def _bib_path():
    return data_dir / "bibliography.json"


def _matching_path():
    return data_dir / "matching_report.json"


def _config_path():
    return data_dir / "config.json"


def _default_config():
    return {
        "source_dir": "./literature_files",
        "output_dir": "./renamed",
        "threshold": 0.30,
        "bibliography_file": "",
        "manual_matches": {},
    }


def _load_config():
    _ensure_data()
    p = _config_path()
    if not p.exists():
        cfg = _default_config()
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return cfg
    return json.loads(p.read_text(encoding="utf-8"))


def _save_config(cfg):
    _ensure_data()
    _config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ── pages ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    bib = _load_bib()
    report_path = _matching_path()
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
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
    src_dir = Path(cfg.get("source_dir", "./literature_files"))
    files = sorted(
        f.name for f in src_dir.rglob("*") if f.is_file() and f.suffix.lower() in {".pdf", ".docx", ".djvu", ".txt"}
    ) if src_dir.exists() else []
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
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
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


# ── API: library management ──────────────────────────────────────────────────
@app.get("/api/info")
async def api_info():
    return {
        "name": "TextAlchemy",
        "version": __import__("textalchemy").__version__,
        "modules": ["extract", "convert", "organize", "generate", "recognize"],
    }


@app.get("/api/bibliography")
async def api_get_bibliography():
    return _load_bib()


@app.post("/api/bibliography")
async def api_add_bib_item(
    authors: str = Form(...),
    title: str = Form(...),
    doc_type: str = Form("article"),
    year: str = Form(""),
    journal: str = Form(""),
    publisher: str = Form(""),
    city: str = Form(""),
    pages: str = Form(""),
    isbn: str = Form(""),
    doi: str = Form(""),
    source: str = Form(""),
):
    items = _load_bib()
    item: dict[str, Any] = {
        "id": None,
        "authors": [a.strip() for a in authors.split(";") if a.strip()],
        "title": title,
        "doc_type": doc_type,
        "year": year,
        "journal": journal,
        "publisher": publisher,
        "city": city,
        "pages": pages,
        "isbn": isbn,
        "doi": doi,
        "source": source,
    }
    items.append(item)
    _save_bib(items)
    return {"success": True, "item": item}


@app.put("/api/bibliography/{item_id}")
async def api_update_bib_item(
    item_id: int,
    authors: str = Form(...),
    title: str = Form(...),
    doc_type: str = Form("article"),
    year: str = Form(""),
    journal: str = Form(""),
    publisher: str = Form(""),
    city: str = Form(""),
    pages: str = Form(""),
    isbn: str = Form(""),
    doi: str = Form(""),
    source: str = Form(""),
):
    items = _load_bib()
    for item in items:
        if item.get("id") == item_id:
            item.update({
                "authors": [a.strip() for a in authors.split(";") if a.strip()],
                "title": title,
                "doc_type": doc_type,
                "year": year,
                "journal": journal,
                "publisher": publisher,
                "city": city,
                "pages": pages,
                "isbn": isbn,
                "doi": doi,
                "source": source,
            })
            _save_bib(items)
            return {"success": True, "item": item}
    raise HTTPException(status_code=404, detail="Item not found")


@app.delete("/api/bibliography/{item_id}")
async def api_delete_bib_item(item_id: int):
    items = _load_bib()
    items = [i for i in items if i.get("id") != item_id]
    _save_bib(items)
    return {"success": True}


@app.post("/api/bibliography/import")
async def api_import_bib(file: UploadFile = File(...)):
    import tempfile

    from textalchemy.organize import BibliographyParser
    fname = file.filename or "import.json"
    tmp = Path(tempfile.mkdtemp()) / fname
    tmp.write_bytes(await file.read())
    try:
        items = BibliographyParser.parse_file(str(tmp))
        data = BibliographyParser.to_json(items)
        existing = _load_bib()
        next_id = max((i.get("id", 0) for i in existing), default=0) + 1
        for i, item in enumerate(data):
            item["id"] = next_id + i
            existing.append(item)
        _save_bib(existing)
        return {"success": True, "count": len(data)}
    finally:
        tmp.unlink(missing_ok=True)


# ── API: smart-parse ────────────────────────────────────────────────────────
@app.post("/api/bibliography/smart-parse")
async def api_smart_parse(text: str = Form(...)):
    from textalchemy.pipeline.bibliography import smart_parse_bibliography
    items = smart_parse_bibliography(text=text)
    return {"success": True, "items": [{"index": i.index, "authors": i.authors, "title": i.title, "year": i.year} for i in items]}


# ── API: pipeline ───────────────────────────────────────────────────────────
@app.post("/api/pipeline/run")
async def api_pipeline_run(spec: str = Form(...)):
    import yaml

    from textalchemy.pipeline.runner import run_pipeline
    try:
        pipeline_def = json.loads(spec)
    except json.JSONDecodeError:
        pipeline_def = yaml.safe_load(spec)
    result = run_pipeline(pipeline_def)
    return {"success": True, "result": result.to_dict()}


# ── API: operations ─────────────────────────────────────────────────────────
@app.get("/api/operations")
async def api_operations():
    from textalchemy.core.registry import all_operations
    return [{"id": op.id, "input_type": op.input_type, "output_type": op.output_type,
             "input_param": op.input_param, "description": op.description, "tags": op.tags}
            for op in all_operations()]


# ── API: matching ────────────────────────────────────────────────────────────
@app.post("/api/match/run")
async def api_run_matching(
    source_dir: str = Form("./literature_files"),
    output_dir: str = Form("./renamed"),
    threshold: float = Form(0.30),
    bibliography_file: str = Form(""),
    dry_run: bool = Form(False),
):
    from textalchemy.pipeline.match_files import match_files

    if bibliography_file:
        from textalchemy.pipeline.bibliography import parse_bibliography
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

    results: dict[str, Any] = {"matched": [], "unmatched": [], "errors": [], "total": len(matches)}
    for m in matches:
        entry = {"file": m.document.path.name}
        if m.matched and m.item is not None:
            from textalchemy.pipeline.name import name_from_match
            new_name = name_from_match(match=m, ext=m.document.path.suffix.lower()) or m.document.path.name
            results["matched"].append({
                "original": m.document.path.name,
                "new": new_name,
                "score": round(m.score, 2) if m.score else 0,
            })
        else:
            results["unmatched"].append(entry)

    _ensure_data()
    _matching_path().write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

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


# ── API: config ──────────────────────────────────────────────────────────────
@app.get("/api/config")
async def api_get_config():
    return _load_config()


@app.post("/api/config")
async def api_update_config(cfg: str = Form(...)):
    _save_config(json.loads(cfg))
    return {"success": True}


# ── API: export ──────────────────────────────────────────────────────────────
@app.get("/api/export/{fmt}")
async def api_export(fmt: str):
    from textalchemy.pipeline.render import render_bibtex, render_gost, render_json, render_markdown

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


# ── API: preview renaming ───────────────────────────────────────────────────
@app.post("/api/preview/rename")
async def api_preview_rename(
    source_dir: str = Form("./literature_files"),
    threshold: float = Form(0.30),
    bibliography_file: str = Form(""),
):
    from textalchemy.pipeline.match_files import match_files
    from textalchemy.pipeline.name import name_from_match

    if bibliography_file:
        from textalchemy.pipeline.bibliography import parse_bibliography
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
            preview.append({
                "original": m.document.path.name,
                "new": new_name,
                "match": True,
                "score": round(m.score, 2) if m.score else 0,
            })
        else:
            preview.append({
                "original": m.document.path.name,
                "new": m.document.path.name,
                "match": False,
                "score": 0,
            })

    return {"preview": preview, "total": len(preview), "matched": sum(1 for p in preview if p["match"])}


# ── API: stats ───────────────────────────────────────────────────────────────
@app.get("/api/stats")
async def api_stats():
    bib = _load_bib()
    cfg = _load_config()
    src = Path(cfg.get("source_dir", "./literature_files"))
    out = Path(cfg.get("output_dir", "./renamed"))
    total_files = len([f for f in src.rglob("*") if f.is_file()]) if src.exists() else 0
    matched_files = len([f for f in out.rglob("*") if f.is_file()]) if out.exists() else 0
    doc_types: dict[str, int] = {}
    for item in bib:
        dt = item.get("doc_type", "unknown")
        doc_types[dt] = doc_types.get(dt, 0) + 1
    report_path = _matching_path()
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
    return {
        "total_bib": len(bib),
        "total_files": total_files,
        "matched_files": matched_files,
        "unmatched": total_files - matched_files,
        "progress": round(matched_files / len(bib) * 100, 1) if bib else 0,
        "doc_types": doc_types,
        "matching": report,
    }


# ── API: extract ─────────────────────────────────────────────────────────────
@app.post("/api/extract/text")
async def api_extract_text(file: UploadFile = File(...), fmt: str = Form("auto")):
    import os
    import tempfile

    from textalchemy.pipeline.extract import extract_text
    from textalchemy.pipeline.ingest import ingest_file

    fname = file.filename or "extracted.txt"
    tmp = Path(tempfile.mkdtemp()) / fname
    tmp.write_bytes(await file.read())
    try:
        doc = ingest_file(path=tmp)
        text = extract_text(doc=doc)
        return {"success": True, "text": text.plain, "filename": file.filename}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        os.unlink(tmp)


@app.post("/api/extract/latex")
async def api_extract_latex(
    file: UploadFile = File(...),
    doc_type: str = Form("manuscript"),
):
    import os
    import tempfile

    from textalchemy.extract import docx_to_latex
    fname = file.filename or "document.docx"
    tmp = Path(tempfile.mkdtemp()) / fname
    tmp.write_bytes(await file.read())
    out = tmp.with_suffix(".tex")
    try:
        docx_to_latex(tmp, out, doc_type)
        content = out.read_text(encoding="utf-8")
        return Response(content=content, media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename={out.name}"})
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        os.unlink(tmp)
        if out.exists():
            os.unlink(out)


# ── Background task management ───────────────────────────────────────────────

_tasks: dict[str, dict[str, Any]] = {}


def _run_convert(task_id: str, src_path: Path, out_path: Path, tool: str, fmt: str):
    import shutil
    import tempfile

    if fmt == "pptx":
        try:
            from textalchemy.convert.pptx_to_html import convert as pptx_to_html
            out_dir = Path(tempfile.mkdtemp())
            pptx_to_html(src_path, out_dir)
            # zip the output directory
            zip_path = out_path.with_suffix(".zip")
            shutil.make_archive(str(zip_path.with_suffix("")), "zip", out_dir)
            content = zip_path.read_bytes()
            import base64
            _tasks[task_id] = {
                "status": "done",
                "content": base64.b64encode(content).decode(),
                "filename": src_path.stem + ".zip",
                "error": None,
            }
            shutil.rmtree(out_dir, ignore_errors=True)
            zip_path.unlink(missing_ok=True)
        except Exception as e:
            _tasks[task_id] = {"status": "error", "error": str(e)}
        finally:
            src_path.unlink(missing_ok=True)
        return

    from textalchemy.convert.pdf_to_docx import create_converter
    try:
        converter = create_converter(tool)
        result = converter.convert(src_path, out_path)
        if result.success:
            content = out_path.read_bytes()
            import base64
            _tasks[task_id] = {
                "status": "done",
                "content": base64.b64encode(content).decode(),
                "filename": out_path.name,
                "error": None,
            }
        else:
            _tasks[task_id] = {"status": "error", "error": result.error}
    except Exception as e:
        _tasks[task_id] = {"status": "error", "error": str(e)}
    finally:
        src_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)


# ── API: convert ─────────────────────────────────────────────────────────────
@app.post("/api/convert")
async def api_convert(background_tasks: BackgroundTasks, file: UploadFile = File(...), tool: str = Form("fanout"), fmt: str = Form("pdf")):
    import tempfile

    task_id = str(uuid.uuid4())
    tmp_dir = Path(tempfile.mkdtemp())
    fname = file.filename or f"document.{fmt}"
    src = tmp_dir / fname
    src.write_bytes(await file.read())

    if fmt == "pptx":
        out = tmp_dir / (src.stem + ".zip")
    else:
        out = tmp_dir / (src.stem + ".docx")

    _tasks[task_id] = {"status": "running", "error": None}
    background_tasks.add_task(_run_convert, task_id, src, out, tool, fmt)
    return {"success": True, "task_id": task_id, "status": "/api/convert/status/" + task_id}


@app.get("/api/convert/status/{task_id}")
async def api_convert_status(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] == "done":
        import base64
        content = base64.b64decode(task["content"])
        fname = task["filename"]
        if fname.endswith(".zip"):
            media_type = "application/zip"
        else:
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    return {"status": task["status"], "error": task.get("error")}


# ── API: recognize ───────────────────────────────────────────────────────────
@app.post("/api/recognize")
async def api_recognize(file: UploadFile = File(...)):
    import os
    import tempfile

    from textalchemy.recognize import OcrEngine
    fname = file.filename or "document.pdf"
    tmp = Path(tempfile.mkdtemp()) / fname
    tmp.write_bytes(await file.read())
    try:
        engine = OcrEngine()
        if engine.is_available:
            result = engine.recognize(tmp)
            return {"success": True, "text": result.text, "confidence": result.confidence, "backend": engine.backend_name}
        return {"success": True, "text": f"[STUB] OCR for: {file.filename}", "confidence": 0.0, "backend": None}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        os.unlink(tmp)


# ── API: generate ────────────────────────────────────────────────────────────
@app.get("/api/generate/templates")
async def api_list_templates():
    from textalchemy.generate import list_templates
    templates_list = list_templates()
    return [{"name": t.name, "description": t.description} for t in templates_list]


@app.post("/api/generate")
async def api_generate(
    template: str = Form(...),
    output: str = Form("output.docx"),
    params: str = Form("{}"),
):
    from textalchemy.generate import generate_document
    try:
        result = generate_document(template, output, json.loads(params))
        return {"success": True, "path": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
