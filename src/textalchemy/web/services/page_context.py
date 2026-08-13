"""Application queries used to build server-rendered page context."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


class PageContextService:
    """Prepare view data without coupling presentation routes to persistence details."""

    def __init__(
        self,
        *,
        load_bibliography: Callable[[], list[dict[str, Any]]],
        load_config: Callable[[], dict[str, Any]],
        matching_path: Callable[[], Path],
    ) -> None:
        self._load_bibliography = load_bibliography
        self._load_config = load_config
        self._matching_path = matching_path

    def dashboard(self) -> dict[str, Any]:
        return {
            "bib_count": len(self._load_bibliography()),
            "report": self._matching_report(),
        }

    def bibliography(self) -> dict[str, Any]:
        return {"bib_items": self._load_bibliography()}

    def matching(self) -> dict[str, Any]:
        bibliography = self._load_bibliography()
        config = self._load_config()
        source = Path(config.get("source_dir", "./literature_files"))
        files = (
            sorted(
                path.name
                for path in source.rglob("*")
                if path.is_file() and path.suffix.lower() in {".pdf", ".docx", ".djvu", ".txt"}
            )
            if source.exists()
            else []
        )
        return {"bib_items": bibliography, "config": config, "files": files}

    def reports(self) -> dict[str, Any]:
        return {
            "bib_items": self._load_bibliography(),
            "config": self._load_config(),
            "report": self._matching_report(),
        }

    def _matching_report(self) -> dict[str, Any] | None:
        path = self._matching_path()
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


__all__ = ["PageContextService"]
