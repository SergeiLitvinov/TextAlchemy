"""Роуты веб-интерфейса разбиты по группам (pages, api, ...).

Импорт этого пакета регистрирует все обработчики на ``textalchemy.web.app.app``.
"""
from __future__ import annotations

from textalchemy.web.routes import (
    bibliography,
    convert,
    convert_jobs,
    convert_preview,
    documentation,
    extract,
    generate,
    localization,
    matching,
    pages,
    pdf_order,
    pipeline,
    recognize,
    task_center,
    template_loops,
    template_source,
    template_variables,
)

# Импорт пакета регистрирует все роуты на ``textalchemy.web.app.app``.
__all__ = [
    "pages", "bibliography", "pipeline", "matching", "extract", "convert", "convert_jobs", "convert_preview",
    "recognize", "generate", "task_center", "localization", "pdf_order", "template_variables", "template_loops",
    "template_source", "documentation",
]
