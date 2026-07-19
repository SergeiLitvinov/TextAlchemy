"""Роуты веб-интерфейса разбиты по группам (pages, api, ...).

Импорт этого пакета регистрирует все обработчики на ``textalchemy.web.app.app``.
"""
from __future__ import annotations

from textalchemy.web.routes import (
    bibliography,
    convert,
    extract,
    generate,
    matching,
    pages,
    pipeline,
    recognize,
)

# Импорт пакета регистрирует все роуты на ``textalchemy.web.app.app``.
__all__ = ["pages", "bibliography", "pipeline", "matching", "extract", "convert", "recognize", "generate"]
