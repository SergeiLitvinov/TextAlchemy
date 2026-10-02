"""Сериализация библиографии без зависимостей от базы данных и HTTP."""

from __future__ import annotations

import io
from dataclasses import dataclass

from textalchemy.core.types import BibItem
from textalchemy.pipeline.render import render_bibtex, render_gost, render_json, render_markdown


@dataclass(frozen=True)
class BibliographyExport:
    content: str
    media_type: str
    filename: str


def export_bibliography(fmt: str, items: list[BibItem]) -> BibliographyExport:
    if fmt == "json":
        content = render_json(items=items)
        media_type = "application/json"
        filename = "bibliography.json"
    elif fmt == "markdown":
        content = render_markdown(items=items)
        media_type = "text/markdown"
        filename = "bibliography.md"
    elif fmt == "gost":
        content = render_gost(items=items)
        media_type = "text/plain; charset=utf-8"
        filename = "bibliography_gost.txt"
    elif fmt == "bibtex":
        content = render_bibtex(items=items)
        media_type = "application/x-bibtex"
        filename = "bibliography.bib"
    elif fmt == "ris":
        lines = []
        for it in items:
            au = it.authors if hasattr(it, "authors") else []
            title = it.title if hasattr(it, "title") else ""
            year = str(it.year) if hasattr(it, "year") and it.year else ""
            dt = it.doc_type if hasattr(it, "doc_type") else "GEN"
            for a in au:
                lines.append(f"AU  - {a}")
            lines.append(f"TI  - {title}")
            lines.append(f"PY  - {year}")
            lines.append(f"TY  - {dt.upper()[:4]}")
            lines.append("ER  -")
            lines.append("")
        content = "\n".join(lines)
        media_type = "application/x-research-info-systems"
        filename = "bibliography.ris"
    elif fmt == "csv":
        import csv

        buffer = io.StringIO()
        w = csv.writer(buffer)
        w.writerow(["id", "authors", "title", "year", "doc_type", "source"])
        for it in items:
            w.writerow(
                [
                    getattr(it, "index", ""),
                    "; ".join(getattr(it, "authors", [])),
                    getattr(it, "title", ""),
                    getattr(it, "year", ""),
                    getattr(it, "doc_type", ""),
                    getattr(it, "source", ""),
                ]
            )
        content = buffer.getvalue()
        media_type = "text/csv"
        filename = "bibliography.csv"
    else:
        raise ValueError("Unsupported format")
    return BibliographyExport(content=content, media_type=media_type, filename=filename)
