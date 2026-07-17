"""Pipeline: стадии конвейера.

Импортируются лениво в CLI, но здесь — ``__all__`` для удобства.
Импорт модулей здесь гарантирует, что все ``@operation``-декораторы
выполнятся при первом обращении к пакету.
"""

from textalchemy.pipeline import (
    bibliography,  # noqa: F401
    emails_op,  # noqa: F401
    extract,  # noqa: F401
    ingest,  # noqa: F401
    match,  # noqa: F401
    match_files,  # noqa: F401
    name,  # noqa: F401
    render,  # noqa: F401
    runner,  # noqa: F401
    signals,  # noqa: F401
)

__all__ = [
    "bibliography",
    "emails_op",
    "extract",
    "ingest",
    "match",
    "match_files",
    "name",
    "render",
    "runner",
    "signals",
]
