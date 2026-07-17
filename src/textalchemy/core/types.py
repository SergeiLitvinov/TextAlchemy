"""Канонические типы данных конвейера.

Все операции работают с этими типами; ``Document`` инкапсулирует файл на диске,
``Text`` — извлечённое содержимое (нормализованное, блочное), ``Match`` —
результат матчинга документа со строкой библиографии.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class DocFormat(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    TXT = "txt"
    DJVU = "djvu"
    BIB = "bib"  # библиография как plain text
    UNKNOWN = "unknown"


class BlockType(str, Enum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    TABLE = "table"
    CAPTION = "caption"
    EQUATION = "equation"
    CODE = "code"
    PAGE_BREAK = "page_break"
    UNKNOWN = "unknown"


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

    @classmethod
    def from_path(cls, path: str | Path) -> "Document":
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(p)
        return cls(
            path=p,
            format=_detect_format(p),
            size=p.stat().st_size,
            sha256="",  # заполняется в pipeline/ingest.py
        )


_EXT_FORMAT = {
    ".pdf": DocFormat.PDF,
    ".docx": DocFormat.DOCX,
    ".pptx": DocFormat.PPTX,
    ".txt": DocFormat.TXT,
    ".djvu": DocFormat.DJVU,
    ".bib": DocFormat.BIB,
}


def _detect_format(path: Path) -> DocFormat:
    return _EXT_FORMAT.get(path.suffix.lower(), DocFormat.UNKNOWN)


@dataclass
class Block:
    """Структурный блок текста (параграф/заголовок/таблица/...)."""

    type: BlockType
    text: str = ""
    level: int = 0
    page: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Table:
    """Таблица как список строк."""

    rows: list[list[str]] = field(default_factory=list)
    page: int = 0


@dataclass
class Text:
    """Извлечённое из документа содержимое.

    Не зависит от исходного формата. ``blocks`` хранит структурную
    разметку; ``plain`` — плоский текст (для grep/fuzzy/keyword); ``tables``
    — таблицы отдельно, чтобы не терять структуру.
    """

    blocks: list[Block] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    plain: str = ""
    language: str = "und"
    source_format: DocFormat = DocFormat.UNKNOWN
    engine: str = ""  # какой движок достал (pdfplumber / pypdf / pymupdf / ...)
    warnings: list[str] = field(default_factory=list)
    pages: int = 0

    def __bool__(self) -> bool:
        return bool(self.plain or self.blocks or self.tables)


@dataclass
class BibItem:
    """Запись библиографии."""

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
    """Результат матчинга документа со строкой библиографии."""

    document: Document
    item: Optional[BibItem]
    signals: list[Signal] = field(default_factory=list)
    matched: bool = False

    @property
    def score(self) -> float:
        return sum(s.contribution for s in self.signals)

    def signal_score(self, name: str) -> float:
        for s in self.signals:
            if s.name == name:
                return s.contribution
        return 0.0


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
]
