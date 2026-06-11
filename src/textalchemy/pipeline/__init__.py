"""Pipeline: стадии конвейера.

Импортируются лениво в CLI, но здесь — ``__all__`` для удобства.
Импорт модулей здесь гарантирует, что все ``@operation``-декораторы
выполнятся при первом обращении к пакету.
"""
from textalchemy.pipeline import (
    extract,  # noqa: F401
    ingest,  # noqa: F401
    match,  # noqa: F401
    name,  # noqa: F401
    render,  # noqa: F401
)

__all__ = ["extract", "ingest", "match", "name", "render", "runner"]
