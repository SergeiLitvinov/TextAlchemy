"""Текстовый ридер с цепочкой fallback-движков.

Стратегия:
  pdfplumber → pypdf → pymupdf (geometry → semantics)

Каждый движок возвращает ``Text`` с заполненным ``engine``. Если движок
бросил исключение, пробуем следующий. Если все упали — ``Text(warnings=[...])``
с пустым содержимым, чтобы пайплайн мог корректно зафиксировать «не смогли».
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from textalchemy.core.types import Block, BlockType, DocFormat, Text
from textalchemy.formats.pdf_geometry import PdfGeometryDocument, extract_pdf_geometry
from textalchemy.formats.pdf_semantic import analyze_pdf_geometry

logger = logging.getLogger(__name__)


def _safe_call(name: str, fn: Callable[[], Text]) -> Text:
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        logger.warning("PDF engine %s failed: %s", name, e)
        return Text(
            source_format=DocFormat.PDF,
            engine=name,
            warnings=[f"{name}: {type(e).__name__}: {e}"],
        )


def _with_pdfplumber(path: str) -> Text:
    import pdfplumber  # type: ignore[import-not-found]

    blocks: list[Block] = []
    pages = 0
    plain_parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text:
                blocks.append(Block(type=BlockType.PARAGRAPH, text=text, page=i))
                plain_parts.append(text)
            for tbl in page.extract_tables() or []:
                rows = [[(c if c is not None else "") for c in row] for row in tbl]

                blocks.append(Block(type=BlockType.TABLE, page=i, meta={"rows": rows}))

    return Text(
        blocks=blocks,
        plain="\n".join(plain_parts),
        source_format=DocFormat.PDF,
        engine="pdfplumber",
        pages=pages,
    )


def _with_pypdf(path: str) -> Text:
    from pypdf import PdfReader

    reader = PdfReader(path)
    plain_parts: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            t = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            t = ""
        if t:
            plain_parts.append(t)
    plain = "\n".join(plain_parts)
    if plain.count("\x00") > len(plain) * 0.1:
        plain = plain.replace("\x00", "").replace("\ufffd", "")
    return Text(
        blocks=[Block(type=BlockType.PARAGRAPH, text=plain)] if plain else [],
        plain=plain,
        source_format=DocFormat.PDF,
        engine="pypdf",
        pages=len(reader.pages),
    )


def _with_pymupdf(path: str) -> Text:
    return analyze_pdf_geometry(extract_pdf_geometry(path))


def read_pdf_geometry(path: str | Path) -> PdfGeometryDocument:
    """Публичный геометрический импорт PDF без семантических эвристик."""

    return extract_pdf_geometry(path)


def read_pdf(path: str) -> Text:
    """Достать текст из PDF: pdfplumber → pypdf → pymupdf.

    Возвращает первый успешный (ненулевой) результат; предупреждения всех
    упавших движков притаскиваются в ``warnings`` итогового ``Text``.
    """
    engines: list[tuple[str, Callable[[str], Text]]] = [
        ("pdfplumber", _with_pdfplumber),
        ("pypdf", _with_pypdf),
        ("pymupdf", _with_pymupdf),
    ]
    warnings: list[str] = []
    for name, fn in engines:
        result = _safe_call(name, lambda: fn(path))
        if result.plain or result.blocks:
            result.warnings = warnings + result.warnings
            return result
        warnings.extend(result.warnings)
    return Text(
        source_format=DocFormat.PDF,
        engine="none",
        warnings=warnings or ["no PDF engine succeeded"],
    )


def get_pdf_info(path: str) -> dict:
    """Извлечь метаданные PDF (title, author, subject) через pypdf."""
    info = {"title": "", "author": "", "subject": ""}
    try:
        from pypdf import PdfReader
        with PdfReader(path) as reader:
            meta = reader.metadata
            if meta:
                info["title"] = getattr(meta, "title", "") or ""
                info["author"] = getattr(meta, "author", "") or ""
                info["subject"] = getattr(meta, "subject", "") or ""
    except Exception:  # noqa: BLE001
        pass
    return info


__all__ = ["get_pdf_info", "read_pdf", "read_pdf_geometry"]
