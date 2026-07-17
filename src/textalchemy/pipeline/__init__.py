"""Pipeline: Entry point for operations.

Operations are registered via CLI, here - in ``__all__`` and via ``@operation`` decorator.
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
    render_html,  # noqa: F401
)

__all__ = [
    "bibliography", "emails_op", "extract", "ingest", "match", "match_files",
    "name", "render", "render_html", "runner",
]
