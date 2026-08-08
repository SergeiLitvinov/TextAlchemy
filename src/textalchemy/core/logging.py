"""Централизованная настройка логирования.

Единственное место, где конфигурируются корневые обработчики и уровни.
Модули-библиотеки создают логгеры через ``logging.getLogger(__name__)``
(они иерархически наследуются от ``textalchemy``), а CLI/Web входа
вызывают :func:`configure_logging` при старте.
"""

from __future__ import annotations

import logging

PACKAGE_NAME = "textalchemy"

CONSOLE_FORMAT = "%(levelname)s: %(message)s"
DEBUG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(*, debug: bool = False, quiet: bool = False) -> None:
    """Настроить корневой логгер пакета один раз (повторные вызовы идемпотентны).

    ``debug`` включает отладочный уровень и подробный формат с именем логгера;
    ``quiet`` подавляет всё, кроме критических ошибок.
    """
    level = logging.ERROR if quiet else (logging.DEBUG if debug else logging.WARNING)
    logging.basicConfig(level=level, format=DEBUG_FORMAT if debug else CONSOLE_FORMAT)
    root = logging.getLogger(PACKAGE_NAME)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Логгер, гарантированно вложенный в пакет ``textalchemy``."""
    if name == PACKAGE_NAME or name.startswith(PACKAGE_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{PACKAGE_NAME}.{name.lstrip('.')}")


__all__ = ["configure_logging", "get_logger", "PACKAGE_NAME"]
