"""Канонические типы данных конвейера.

Все операции работают с этими типами; ``Document`` инкапсулирует файл на диске,
``Text`` — извлечённое содержимое (нормализованное, блочное), ``Match`` —
результат матчинга документа со строкой библиографии.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from opendoc_formats.types import Block, BlockType, DocFormat, Table, Text


@dataclass(frozen=True)
class Document:
    """Файл, готовый к обработке конвейером.

    Не хранит содержимое — это ссылка + метаданные, полученные на стадии
    ``ingest``. Содержимое извлекается отдельно и попадает в ``Text``.
    """

    path: Path
    format: DocFormat
    size: int
    sha256: str
    encoding: str = "utf-8"

    def __post_init__(self):
        # Лениво вычисляем хеш, если он не задан явно.
        if not self.sha256 and Path(self.path).is_file():
            from textalchemy.core.io import compute_hash

            object.__setattr__(self, "sha256", compute_hash(self.path))

    @classmethod
    def from_path(cls, path: str | Path) -> "Document":
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(p)
        return cls(
            path=p,
            format=_detect_format(p),
            size=p.stat().st_size,
            sha256="",  # заполняется в __post_init__
        )


_EXT_FORMAT = {
    ".pdf": DocFormat.PDF,
    ".docx": DocFormat.DOCX,
    ".pptx": DocFormat.PPTX,
    ".txt": DocFormat.TXT,
    ".djvu": DocFormat.DJVU,
    ".epub": DocFormat.EPUB,
    ".bib": DocFormat.BIB,
}


def _detect_format(path: Path) -> DocFormat:
    return _EXT_FORMAT.get(path.suffix.lower(), DocFormat.UNKNOWN)


@dataclass
class BibItem:
    """Запись библиографии. Единый класс для всего приложения."""

    index: int = 0
    raw_text: str = ""
    authors: list[str] = field(default_factory=list)
    title: str = ""
    year: Optional[int] = None
    doc_type: str = "unknown"
    source: str = ""
    pages: str = ""
    doi: str = ""
    isbn: str = ""
    url: str = ""
    journal: str = ""
    publisher: str = ""
    city: str = ""

    # Поля, сериализуемые в словарь (порядок важен для UI/БД).
    _FIELDS = (
        "index",
        "raw_text",
        "authors",
        "title",
        "year",
        "doc_type",
        "source",
        "pages",
        "doi",
        "isbn",
        "url",
        "journal",
        "publisher",
        "city",
    )

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self._FIELDS}

    @classmethod
    def from_dict(cls, d: dict) -> "BibItem":
        year_raw = d.get("year", "")
        year = int(year_raw) if year_raw not in (None, "") and str(year_raw).strip().isdigit() else None
        item_id = d.get("id")
        try:
            index = int(item_id) if item_id not in (None, "") else (d.get("index") or 0)
        except (TypeError, ValueError):
            index = d.get("index") or 0
        raw_authors = d.get("authors", [])
        authors = [raw_authors] if isinstance(raw_authors, str) else list(raw_authors)
        return cls(
            index=index,
            raw_text=d.get("raw_text", ""),
            authors=authors,
            title=d.get("title", ""),
            year=year,
            doc_type=d.get("doc_type", "unknown"),
            source=d.get("source", ""),
            pages=d.get("pages", ""),
            doi=d.get("doi", ""),
            isbn=d.get("isbn", ""),
            url=d.get("url", ""),
            journal=d.get("journal", ""),
            publisher=d.get("publisher", ""),
            city=d.get("city", ""),
        )


@dataclass
class Signal:
    """Один сигнал матчинга: вклад одного правила в итоговый score."""

    name: str
    score: float
    weight: float = 1.0
    detail: str = ""

    @property
    def contribution(self) -> float:
        return self.score * self.weight


@dataclass
class Match:
    """Результат матчинга; copied_path заполняется только после успешного копирования."""

    document: Document
    item: Optional[BibItem]
    signals: list[Signal] = field(default_factory=list)
    matched: bool = False
    copied_path: Optional[Path] = None

    @property
    def score(self) -> float:
        return sum(s.contribution for s in self.signals)

    def signal_score(self, name: str) -> float:
        for s in self.signals:
            if s.name == name:
                return s.contribution
        return 0.0


@dataclass
class OperationResult:
    """Обёртка результата операции — значение + предупреждения + метрики."""

    value: Any
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "DocFormat",
    "BlockType",
    "Document",
    "Block",
    "Table",
    "Text",
    "BibItem",
    "Signal",
    "Match",
    "OperationResult",
]
