"""Точка входа веб-приложения.

Всё состояние (``app``, ``templates``, ``db``, helpers) — в ``textalchemy.web.app``,
все роуты — в ``textalchemy.web.routes``. Этот модуль только регистрирует роуты
и экспортирует ``app`` для запуска через ``uvicorn textalchemy.web.main:app``.
"""
from __future__ import annotations

from textalchemy.web import routes  # noqa: F401 — регистрирует роуты
from textalchemy.web.app import app

__all__ = ["app"]
