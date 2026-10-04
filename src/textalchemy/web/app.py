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
from textalchemy.web.runtime import configure_worker_processes
from textalchemy.web.services.bibliography import BibliographyService
from textalchemy.web.services.matching import MatchingService
from textalchemy.web.tasks import TaskStore

_VERSION = __version__
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    del application
    configure_worker_processes()
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
_asset_revision = max((path.stat().st_mtime_ns for path in static_dir.rglob("*") if path.is_file()), default=0)
env.globals["asset_version"] = f"{__version__}.{_asset_revision}"
templates = Jinja2Templates(env=env)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Database
db = Database(db_path=data_dir / "library.db")


# ── helpers ──────────────────────────────────────────────────────────────────
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
    return _bibliography_service().list_items()


def _bibliography_service() -> BibliographyService:
    _ensure_data()
    _migrate_json_to_db()
    return BibliographyService(db)


def _bib_path():
    return data_dir / "bibliography.json"


def _matching_path():
    return data_dir / "matching_report.json"


def matching_service() -> MatchingService:
    _ensure_data()
    _migrate_json_to_db()
    return MatchingService(db, report_path=_matching_path(), load_config=_load_config, save_config=_save_config)


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


def _run_persisted_conversion(task_id: str) -> None:
    """Execute a durable conversion without depending on the HTTP route layer."""
    conversion_task_service().run_stored(task_id)


def conversion_task_service():
    """Собрать прикладной сервис конвертации в composition root."""
    from textalchemy.core.inspection import compare_inspections, inspect_path
    from textalchemy.web.services.conversion_tasks import ConversionTaskService
    from textalchemy.web.workspace import create_web_workspace

    return ConversionTaskService(
        store=tasks_store,
        queue=task_queue,
        workspace_factory=create_web_workspace,
        inspector=inspect_path,
        comparer=compare_inspections,
    )


def resume_conversion_task(task_id: str) -> None:
    """Submit a durable conversion during normal work or lifespan recovery."""
    task_queue.submit_named(task_id, _run_persisted_conversion, task_id)


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
    "_dict_to_bibitem",
    "_ensure_data",
    "_migrate_json_to_db",
    "_load_bib",
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
