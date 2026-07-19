"""Сигналы матчинга: каждое правило отдельно, веса — конфигурируемые.

Идея: разбить хрупкую эвристику ``match_file_to_bibliography`` на набор
изолированных сигналов. Каждый сигнал — функция ``(text, filename, item) → Signal``.
Итоговый ``Match`` — сумма вкладов. Это позволяет:

* тестировать каждое правило отдельно;
* калибровать веса по факту (после разметки);
* сообщать в отчёте, *почему* документ не совпал (какие сигналы промахнулись).
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

from textalchemy.core.types import BibItem, Signal
from textalchemy.pipeline.name import transliterate

# Веса по умолчанию. Их можно переопределить через ``MatchingConfig`` (TBD).
DEFAULT_WEIGHTS: dict[str, float] = {
    "manual": 100.0,
    "author": 1.0,
    "author_translit": 0.9,
    "author_in_filename": 1.2,
    "author_translit_in_filename": 1.1,
    "title_overlap": 2.0,
    "title_in_filename": 1.5,
    "title_translit_in_filename": 2.5,
    "year": 0.15,
    "doi": 2.0,
    "isbn": 1.5,
}


_RU = "а-яА-ЯёЁa-zA-Z"
_KEYWORD_RE = re.compile(rf"[{_RU}]{{4,}}")


def _normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(rf"[^\w\s{_RU}]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _keywords(text: str, max_n: int = 30) -> set[str]:
    return set(_KEYWORD_RE.findall(_normalize(text)))


def author_match(
    author: str,
    text: str,
    filename: str,
    *,
    threshold: float = 0.6,
) -> Signal:
    """Совпадение по автору. Учитывает транслитерацию (как старая эвристика).

    Возвращает агрегированный Signal с именем ``author`` (макс. вклад).
    Отдельные вклады транслитерации отражаются в ``detail``.
    """
    if not author or len(author) <= 3:
        return Signal(name="author", score=0.0, detail=f"author too short: {author!r}")
    a = _normalize(author)
    t = _normalize(text)
    f = _normalize(filename)
    at = transliterate(author).lower()
    score = 0.0
    matched_in: list[str] = []
    if a in t:
        score = max(score, 1.0)
        matched_in.append("text")
    if at in t:
        score = max(score, 0.9)
        matched_in.append("text_translit")
    if a in f:
        score = max(score, 1.2)
        matched_in.append("filename")
    if at in f:
        score = max(score, 1.1)
        matched_in.append("filename_translit")
    if not matched_in:
        for w in t.split():
            if len(w) >= 4 and SequenceMatcher(None, a, w).ratio() >= threshold:
                score = max(score, 0.8)
                matched_in.append(f"fuzzy:{w}")
                break
    return Signal(
        name="author",
        score=score,
        detail=f"author={author!r} matched in {matched_in or 'none'}",
    )


def title_overlap(title: str, text: str, filename: str) -> Signal:
    """Пересечение ключевых слов заголовка и текста/имени файла."""
    if not title or title in ("Unknown", ""):
        return Signal(name="title_overlap", score=0.0, detail="no title")
    tk = _keywords(title)
    if not tk:
        return Signal(name="title_overlap", score=0.0, detail="no keywords")
    text_kw = _keywords(text)
    file_kw = _keywords(filename)
    text_overlap = len(tk & text_kw) / max(len(tk), 1)
    file_overlap = len(tk & file_kw) / max(len(tk), 1)
    score = max(text_overlap, file_overlap * 1.25)  # имя файла «весомее»
    return Signal(
        name="title_overlap",
        score=score,
        detail=f"text={text_overlap:.2f} file={file_overlap:.2f}",
    )


def title_in_filename(
    title: str,
    filename: str,
    *,
    min_len: int = 15,
    is_empty: bool = False,
) -> Signal:
    """Заголовок (или его начало) дословно встречается в имени файла.

    Для пустых документов (мало текста) совпадение по имени файла весит больше
    (перенесено из старой эвристики ``match_file_to_bibliography``).
    """
    if not title or len(title) < min_len or not filename:
        return Signal(name="title_in_filename", score=0.0, detail="skip")
    tn = _normalize(title)
    fn = _normalize(filename).replace(" ", "_")
    head = tn[: min(60, len(tn))].replace(" ", "_")
    if head and head in fn:
        score = 2.0 if is_empty else 1.0
        return Signal(name="title_in_filename", score=score, detail=f"head={head!r}")
    tt = transliterate(title).lower().replace(" ", "_")
    if len(title) > min_len and tt and (tt in fn):
        score = 2.5 if is_empty else 1.0
        return Signal(name="title_translit_in_filename", score=score, detail=f"translit_head={tt!r}")
    return Signal(name="title_in_filename", score=0.0, detail="no head match")


def year_match(year: Optional[int], text: str, filename: str) -> Signal:
    if year is None:
        return Signal(name="year", score=0.0, detail="no year")
    ys = str(year)
    if ys in text or ys in filename:
        return Signal(name="year", score=1.0, detail=ys)
    return Signal(name="year", score=0.0, detail=ys)


def doi_match(doi: str, text: str) -> Signal:
    if not doi:
        return Signal(name="doi", score=0.0, detail="no doi")
    if doi.lower() in text.lower():
        return Signal(name="doi", score=1.0, detail=doi)
    return Signal(name="doi", score=0.0, detail=doi)


def isbn_match(isbn: str, text: str) -> Signal:
    if not isbn:
        return Signal(name="isbn", score=0.0, detail="no isbn")
    digits = re.sub(r"\D", "", isbn)
    if not digits:
        return Signal(name="isbn", score=0.0, detail="no digits")
    if digits in re.sub(r"\D", "", text):
        return Signal(name="isbn", score=1.0, detail=digits)
    return Signal(name="isbn", score=0.0, detail=digits)


def manual_match(filename: str, items: list[BibItem], mapping: dict[str, int]) -> Signal:
    """Ручной override: имя файла → индекс bibitem (1-based)."""
    if not mapping or not filename:
        return Signal(name="manual", score=0.0, detail="no mapping")
    stem = re.sub(r"\.[^.]+$", "", filename)
    if stem in mapping:
        idx = mapping[stem] - 1
        if 0 <= idx < len(items):
            return Signal(name="manual", score=1.0, detail=f"item[{idx}]")
    return Signal(name="manual", score=0.0, detail="no manual match")


def collect_signals(
    *,
    text: str,
    filename: str,
    item: BibItem,
    manual: Optional[dict[str, int]] = None,
    weights: Optional[dict[str, float]] = None,
    is_empty: bool = False,
) -> list[Signal]:
    """Собрать все сигналы для одного ``(документ, item)``.

    ``manual`` здесь не оценивается (это per-document override, см. ``match``).
    Параметр существует для совместимости сигнатуры вызова.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    raw: list[Signal] = []
    for author in (item.authors or [])[:5]:
        s = author_match(author, text, filename)
        s.weight = w.get("author", 1.0)
        raw.append(s)
    s = title_overlap(item.title, text, filename)
    s.weight = w.get("title_overlap", 2.0)
    raw.append(s)
    s = title_in_filename(item.title, filename, is_empty=is_empty)
    s.weight = w.get("title_in_filename", 1.5)
    raw.append(s)
    s = year_match(item.year, text, filename)
    s.weight = w.get("year", 0.15)
    raw.append(s)
    s = doi_match(item.doi, text)
    s.weight = w.get("doi", 2.0)
    raw.append(s)
    s = isbn_match(item.isbn, text)
    s.weight = w.get("isbn", 1.5)
    raw.append(s)
    return raw


__all__ = [
    "DEFAULT_WEIGHTS",
    "author_match",
    "title_overlap",
    "title_in_filename",
    "year_match",
    "doi_match",
    "isbn_match",
    "manual_match",
    "collect_signals",
]
