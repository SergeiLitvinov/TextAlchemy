"""Locale catalogs for the Web presentation layer."""

from __future__ import annotations

from typing import Any

DEFAULT_LOCALE = "ru"
SUPPORTED_LOCALES = {"ru": "Русский"}

_RU_MESSAGES = {
    "nav.overview": "Обзор",
    "nav.convert": "Преобразовать",
    "nav.generate": "Создать по шаблону",
    "nav.recognize": "Распознать скан",
    "nav.quality": "Проверить качество",
    "nav.automate": "Автоматизировать",
    "nav.sources": "Источники",
    "nav.match": "Связать файлы",
    "nav.export": "Экспортировать",
    "nav.extract": "Извлечь содержимое",
    "header.tasks": "Задачи",
    "header.new_conversion": "Новая конвертация",
}


def locale_catalog(code: str) -> dict[str, Any] | None:
    if code != DEFAULT_LOCALE:
        return None
    return {
        "code": DEFAULT_LOCALE,
        "name": SUPPORTED_LOCALES[DEFAULT_LOCALE],
        "messages": _RU_MESSAGES,
    }


def locale_manifest() -> dict[str, Any]:
    return {
        "default": DEFAULT_LOCALE,
        "locales": [{"code": code, "name": name} for code, name in SUPPORTED_LOCALES.items()],
    }


__all__ = ["DEFAULT_LOCALE", "SUPPORTED_LOCALES", "locale_catalog", "locale_manifest"]
