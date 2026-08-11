"""Общее состояние веб-приложения: app, templates, db, data_dir, helpers.

Выделено из ``main.py``, чтобы роуты (``web/routes/*.py``) могли импортировать
общие объекты без циклических зависимостей.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import platformdirs
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

from textalchemy import __version__
from textalchemy.core.database import Database
from textalchemy.organize.bibliography import BibItem
from textalchemy.web.queue import recover_persisted_tasks, task_queue
from textalchemy.web.tasks import TaskStore

_VERSION = __version__
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    del application
    # Lazy import avoids the app/routes import cycle while allowing persisted
    # conversion descriptors to be requeued after a process restart.
    from textalchemy.web.routes.convert import resume_conversion_task

    recovery = recover_persisted_tasks(tasks_store, {"convert": resume_conversion_task})
    if recovery.resumed:
        logger.info("Возобновлено %d задач после перезапуска", recovery.resumed)
    if recovery.interrupted:
        logger.warning("Помечено %d невосстановимых задач", recovery.interrupted)
    yield


app = FastAPI(
    title="TextAlchemy",
    description="Универсальный инструментарий обработки научно-учебных документов.\n\n"
    "Модули: extract (DOCX→текст/LaTeX), convert (PDF→DOCX), organize (библиография + ренейм + ГОСТ), "
    "recognize (OCR), generate (шаблоны).\n\n"
    "Все API-эндпоинты доступны под /api/. Веб-интерфейс — статические HTML-страницы.",
    version=_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=_lifespan,
)

templates_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"
# Данные (БД, отчёты, конфиг) живут в user-data dir, а не в CWD пользователя.
data_dir = Path(platformdirs.user_data_dir("textalchemy", "textalchemy"))

env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True, cache_size=0)
env.globals["asset_version"] = __version__
templates = Jinja2Templates(env=env)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Database
db = Database(db_path=data_dir / "library.db")


# ── helpers ──────────────────────────────────────────────────────────────────
def _bibitem_to_dict(item: BibItem) -> dict[str, Any]:
    d = item.to_dict()
    d["id"] = item.index
    d["year"] = str(item.year) if item.year is not None else ""
    return d


def _dict_to_bibitem(d: dict, item_id: int | None = None) -> BibItem:
    if item_id is not None:
        d = {**d, "id": item_id}
    return BibItem.from_dict(d)


def _ensure_data():
    data_dir.mkdir(parents=True, exist_ok=True)


def _migrate_json_to_db():
    """Import a legacy JSON bibliography, preserving and diagnosing failures."""
    p = data_dir / "bibliography.json"
    if not p.exists() or db.all_items():
        return
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
            raise ValueError("bibliography.json must contain a list of objects")
        items = [_dict_to_bibitem(item) for item in raw]
        db.add_items(items)
        p.rename(data_dir / "bibliography.json.imported")
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        logger.exception("Failed to migrate legacy bibliography from %s; source file was preserved", p)


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
    from textalchemy.core.io import atomic_write_text

    _ensure_data()
    p = _config_path()
    if not p.exists():
        cfg = _default_config()
        atomic_write_text(p, json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return cfg
    return json.loads(p.read_text(encoding="utf-8"))


def _save_config(cfg):
    from textalchemy.core.io import atomic_write_text

    _ensure_data()
    atomic_write_text(_config_path(), json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Background task management ───────────────────────────────────────────────
# Задачи и их артефакты живут на диске в data_dir/tasks (переживают перезапуск,
# не держат байты результата в памяти). Просроченные удаляются по TTL.
_TASK_TTL_SECONDS = 3600
tasks_store = TaskStore(data_dir / "tasks", ttl_seconds=_TASK_TTL_SECONDS)


def _prune_tasks() -> int:
    return tasks_store.prune()


def _register_task(task_id: str, payload: dict[str, Any]) -> None:
    tasks_store.set(task_id, payload)


__all__ = [
    "app",
    "templates",
    "db",
    "data_dir",
    "templates_dir",
    "static_dir",
    "_VERSION",
    "_bibitem_to_dict",
    "_dict_to_bibitem",
    "_ensure_data",
    "_migrate_json_to_db",
    "_load_bib",
    "_save_bib",
    "_bib_path",
    "_matching_path",
    "_config_path",
    "_default_config",
    "_load_config",
    "_save_config",
    "tasks_store",
    "task_queue",
    "_register_task",
    "_prune_tasks",
]
