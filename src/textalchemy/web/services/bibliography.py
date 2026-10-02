"""Bibliography use cases, independent of HTTP and Web application state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from textalchemy.core.types import BibItem
from textalchemy.organize.bibliography import BibliographyParser
from textalchemy.pipeline.bibliography import smart_parse_bibliography
from textalchemy.web.services.bibliography_export import BibliographyExport, export_bibliography


class BibliographyRepository(Protocol):
    def all_items(self) -> list[BibItem]: ...

    def get_item(self, item_id: int) -> BibItem | None: ...

    def add_item(self, item: BibItem) -> BibItem: ...

    def add_items(self, items: list[BibItem]) -> list[BibItem]: ...

    def update_item(self, item_id: int, item: BibItem) -> bool: ...

    def delete_item(self, item_id: int) -> bool: ...


@dataclass(frozen=True, kw_only=True)
class BibliographyInput:
    authors: str
    title: str
    doc_type: str = "article"
    year: str = ""
    journal: str = ""
    publisher: str = ""
    city: str = ""
    pages: str = ""
    isbn: str = ""
    doi: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["authors"] = [author.strip() for author in self.authors.split(";") if author.strip()]
        return value


def bibliography_record(item: BibItem) -> dict[str, Any]:
    """The existing Web record format, including a string year and database id."""
    value = item.to_dict()
    value["id"] = item.index
    value["year"] = str(item.year) if item.year is not None else ""
    return value


class BibliographyService:
    def __init__(self, repository: BibliographyRepository) -> None:
        self._repository = repository

    def list_items(self) -> list[dict[str, Any]]:
        return [bibliography_record(item) for item in self._repository.all_items()]

    def export(self, fmt: str) -> BibliographyExport:
        return export_bibliography(fmt, self._repository.all_items())

    def add(self, fields: BibliographyInput) -> dict[str, Any]:
        value = fields.to_dict()
        added = self._repository.add_item(BibItem.from_dict(value))
        return {"success": True, "item": {"id": added.index, **value}}

    def update(self, item_id: int, fields: BibliographyInput) -> dict[str, Any]:
        existing = self._repository.get_item(item_id)
        if existing is None:
            raise LookupError("Item not found")
        value = bibliography_record(existing)
        value.update(fields.to_dict())
        if not self._repository.update_item(item_id, BibItem.from_dict(value)):
            raise LookupError("Item not found")
        return {"success": True, "item": value}

    def delete(self, item_id: int) -> dict[str, bool]:
        self._repository.delete_item(item_id)
        return {"success": True}

    def import_file(self, path: Path) -> dict[str, Any]:
        items = BibliographyParser.parse_file(str(path))
        for item in items:
            item.index = 0
        self._repository.add_items(items)
        return {"success": True, "count": len(items)}

    def smart_parse(self, text: str) -> dict[str, Any]:
        items = smart_parse_bibliography(text=text)
        return {
            "success": True,
            "items": [{"index": item.index, "authors": item.authors, "title": item.title, "year": item.year} for item in items],
        }


__all__ = ["BibliographyInput", "BibliographyRepository", "BibliographyService", "bibliography_record"]
