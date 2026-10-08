"""Сопоставление, отчёты и статистика без HTTP и глобального состояния Web."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from textalchemy.core.io import atomic_write_text
from textalchemy.core.types import Match
from textalchemy.pipeline.bibliography import parse_bibliography
from textalchemy.pipeline.match_files import match_files
from textalchemy.pipeline.name import name_from_match
from textalchemy.web.services.bibliography import BibliographyRepository


class MatchingService:
    def __init__(
        self,
        repository: BibliographyRepository,
        *,
        report_path: Path,
        load_config: Callable[[], dict[str, Any]],
        save_config: Callable[[dict[str, Any]], None],
    ) -> None:
        self.repository = repository
        self.report_path = report_path
        self.load_config = load_config
        self.save_config = save_config

    def _matches(
        self, *, source_dir: str, threshold: float, bibliography_file: str, output_dir: str | None = None
    ) -> list[Match]:
        items = parse_bibliography(path=bibliography_file) if bibliography_file else self.repository.all_items()
        manual = self.load_config().get("manual_matches", {})
        return match_files(
            source=source_dir,
            items=items,
            threshold=threshold,
            manual=manual,
            output_dir=output_dir,
            copy=output_dir is not None,
        )

    def run(
        self,
        *,
        source_dir: str,
        output_dir: str,
        threshold: float,
        bibliography_file: str,
        dry_run: bool,
    ) -> dict[str, Any]:
        matches = self._matches(
            source_dir=source_dir,
            threshold=threshold,
            bibliography_file=bibliography_file,
            output_dir=None if dry_run else output_dir,
        )
        results: dict[str, Any] = {"matched": [], "unmatched": [], "errors": [], "total": len(matches), "dry_run": dry_run}
        for match in matches:
            original = match.document.path.name
            if match.matched and match.item is not None:
                planned = name_from_match(match=match, ext=match.document.path.suffix.lower()) or original
                copied = match.copied_path
                results["matched"].append(
                    {
                        "original": original,
                        "new": copied.name if copied else None,
                        "planned_name": planned,
                        "copied_path": str(copied) if copied else None,
                        "copied": copied is not None,
                        "match": True,
                        "score": round(match.score, 2),
                        "source": {"title": match.item.title, "authors": match.item.authors, "year": match.item.year},
                    }
                )
                if not dry_run and copied is None:
                    results["errors"].append({"file": original, "code": "copy_failed", "message": "Не удалось создать копию"})
            else:
                results["unmatched"].append({"file": original})
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.report_path, json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        config = self.load_config()
        config.update(source_dir=source_dir, output_dir=output_dir, threshold=threshold)
        if bibliography_file:
            config["bibliography_file"] = bibliography_file
        self.save_config(config)
        return {"success": not results["errors"], **results}

    def report(self) -> dict[str, Any]:
        if not self.report_path.exists():
            return {"matched": [], "unmatched": [], "errors": [], "total": 0}
        return json.loads(self.report_path.read_text(encoding="utf-8"))

    def preview(self, *, source_dir: str, threshold: float, bibliography_file: str) -> dict[str, Any]:
        matches = self._matches(source_dir=source_dir, threshold=threshold, bibliography_file=bibliography_file)
        preview = []
        for match in matches:
            matched = match.matched and match.item is not None
            name = name_from_match(match=match, ext=match.document.path.suffix.lower()) if matched else None
            preview.append(
                {
                    "original": match.document.path.name,
                    "new": name or match.document.path.name,
                    "match": matched,
                    "score": round(match.score, 2) if matched else 0,
                    "source": {"title": match.item.title, "authors": match.item.authors, "year": match.item.year}
                    if matched
                    else None,
                }
            )
        return {"preview": preview, "total": len(preview), "matched": sum(item["match"] for item in preview)}

    def stats(self) -> dict[str, Any]:
        items = self.repository.all_items()
        config = self.load_config()
        source = Path(config.get("source_dir", "./literature_files"))
        output = Path(config.get("output_dir", "./renamed"))
        total = sum(path.is_file() for path in source.rglob("*")) if source.exists() else 0
        copied = sum(path.is_file() for path in output.rglob("*")) if output.exists() else 0
        return {
            "total_bib": len(items),
            "total_files": total,
            "matched_files": copied,
            "unmatched": max(0, total - copied),
            "progress": min(100, round(copied / len(items) * 100, 1)) if items else 0,
            "doc_types": dict(Counter(item.doc_type for item in items)),
            "matching": self.report() if self.report_path.exists() else None,
        }
