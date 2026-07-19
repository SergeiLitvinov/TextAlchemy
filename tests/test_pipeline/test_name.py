"""Тесты pipeline.name."""
from __future__ import annotations

from pathlib import Path

import pytest

from textalchemy.core.types import BibItem, DocFormat, Document, Match, Signal
from textalchemy.pipeline.name import (
    DocType,
    abbreviate_title,
    build_filename,
    format_authors,
    name_from_match,
)


def _item(**kw) -> BibItem:
    base = dict(
        index=1, raw_text="x", authors=[], title="", year=None,
        doc_type="article", source="", pages="", doi="", isbn="", url="",
    )
    base.update(kw)
    return BibItem(**base)


class TestDocType:
    def test_known(self):
        assert DocType.from_str("article") == DocType.ARTICLE
        assert DocType.from_str("ARTICLE") == DocType.ARTICLE
        assert DocType.from_str("xyz") == DocType.UNKNOWN

    def test_short_rus(self):
        assert DocType.ARTICLE.short_rus() == "статья"
        assert DocType.BOOK.short_rus() == "книга"


class TestAbbreviateTitle:
    def test_empty(self):
        assert abbreviate_title("") == ""

    def test_strips_punct(self):
        assert abbreviate_title("Hello, world!") == "hello_world"

    def test_abbreviates_long_words(self):
        # Длинные слова должны аббревиатуриться
        out = abbreviate_title("информационные технологии моделирования")
        # Либо через суффикс-правило, либо обрезкой до 7
        assert any("информ" in part or "инф" in part for part in out.split("_"))


class TestFormatAuthors:
    def test_empty(self):
        assert format_authors([]) == "Unknown"

    def test_single(self):
        assert format_authors(["Иванов"]) == "Иванов"

    def test_truncates_with_et_al(self):
        out = format_authors(["Иванов", "Петров", "Сидоров", "Кузнецов"], max_count=2)
        assert "Иванов" in out
        assert "и_др" in out

    def test_et_al_for_english(self):
        out = format_authors(["Smith", "Jones", "Brown"], max_count=2)
        assert "et_al" in out


class TestBuildFilename:
    def test_basic(self):
        item = _item(index=1, authors=["Иванов"], title="Ferroresonance in Power Grids",
                     doc_type="article")
        name = build_filename(item, ext=".pdf")
        assert name.endswith(".pdf")
        assert "01_" in name
        assert "Иванов" in name

    def test_missing_template_keys_raises(self):
        item = _item()
        with pytest.raises(ValueError):
            build_filename(item, template="{index}")

    def test_include_type_false(self):
        item = _item(index=1, authors=["Иванов"], title="Hello", doc_type="article")
        name = build_filename(item, ext=".pdf", include_type=False)
        # type отсутствует
        assert "статья" not in name

    def test_include_type_false_allows_template_without_type(self):
        item = _item(index=1, authors=["Иванов"], title="Hello", doc_type="article")
        name = build_filename(
            item, ext=".pdf", include_type=False,
            template="{index:02d}_{authors}_{title}",
        )
        assert "статья" not in name
        assert name.startswith("01_")
        assert name.endswith(".pdf")


def _match(matched: bool, item: BibItem | None) -> Match:
    doc = Document(path=Path("/x.pdf"), format=DocFormat.PDF, size=0, sha256="")
    return Match(document=doc, item=item, signals=[Signal("a", 1.0, 1.0)] if matched else [], matched=matched)


class TestNameFromMatch:
    def test_matched(self):
        item = _item(index=1, authors=["Иванов"], title="Hello", doc_type="article")
        name = name_from_match(match=_match(True, item), ext=".pdf")
        assert name is not None
        assert name.endswith(".pdf")
        assert "Иванов" in name

    def test_not_matched_returns_none_by_default(self):
        item = _item(index=1, authors=["Иванов"], title="Hello", doc_type="article")
        name = name_from_match(match=_match(False, item), ext=".pdf")
        assert name is None

    def test_not_matched_returns_name_when_require_false(self):
        item = _item(index=1, authors=["Иванов"], title="Hello", doc_type="article")
        name = name_from_match(match=_match(False, item), ext=".pdf", require_match=False)
        assert name is not None


class TestNameRegistry:
    def test_registered(self):
        from textalchemy.core.registry import all_operations

        ids = {s.id for s in all_operations()}
        assert "name.from_match" in ids
