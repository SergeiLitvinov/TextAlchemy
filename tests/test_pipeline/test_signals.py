"""Тесты pipeline.signals — самое хрупкое место прототипа."""
from __future__ import annotations

from textalchemy.core.types import BibItem
from textalchemy.pipeline.signals import (
    author_match,
    collect_signals,
    doi_match,
    isbn_match,
    manual_match,
    title_in_filename,
    title_overlap,
    year_match,
)


def _item(**kw):
    base = dict(
        index=1, raw_text="x", authors=[], title="", year=None,
        doc_type="unknown", source="", pages="", doi="", isbn="", url="",
    )
    base.update(kw)
    return BibItem(**base)


class TestAuthorMatch:
    def test_exact_in_text(self):
        s = author_match("Иванов", "Работа Иванова И.И.", "f.pdf")
        assert s.score >= 1.0

    def test_in_filename(self):
        s = author_match("Petrov", "Other text", "Petrov_paper.pdf")
        assert s.score >= 1.0

    def test_short_author_skipped(self):
        s = author_match("Li", "text", "f.pdf")
        assert s.score == 0.0

    def test_no_match(self):
        s = author_match("Иванов", "Other text", "Other.pdf")
        assert s.score == 0.0


class TestTitleOverlap:
    def test_clear_overlap(self):
        s = title_overlap(
            "Ferroresonance in Power Grids",
            "This paper studies ferroresonance in power grids carefully",
            "f.pdf",
        )
        assert s.score > 0.5

    def test_no_overlap(self):
        s = title_overlap(
            "Ferroresonance in Power Grids",
            "Completely different topic entirely",
            "f.pdf",
        )
        assert s.score == 0.0

    def test_unknown_title(self):
        s = title_overlap("Unknown", "text", "f.pdf")
        assert s.score == 0.0


class TestTitleInFilename:
    def test_prefix_in_filename(self):
        s = title_in_filename(
            "Long Comprehensive Title Of The Work",
            "Long_Comprehensive_Title_Of_The_Work_2020.pdf",
            min_len=10,
        )
        assert s.score == 1.0

    def test_no_match(self):
        s = title_in_filename("Long Title Here", "other_file.pdf", min_len=10)
        assert s.score == 0.0

    def test_short_title_skipped(self):
        s = title_in_filename("ABC", "abc_file.pdf", min_len=10)
        assert s.score == 0.0


class TestYearMatch:
    def test_match(self):
        assert year_match(2020, "published in 2020", "f.pdf").score == 1.0

    def test_no_match(self):
        assert year_match(2020, "published in 2019", "f.pdf").score == 0.0

    def test_none_year(self):
        assert year_match(None, "text", "f.pdf").score == 0.0


class TestDoiMatch:
    def test_match(self):
        assert doi_match("10.1109/abc.2020", "see DOI: 10.1109/abc.2020 ...").score == 1.0

    def test_no_match(self):
        assert doi_match("10.1109/abc.2020", "no doi here").score == 0.0

    def test_empty(self):
        assert doi_match("", "x").score == 0.0


class TestIsbnMatch:
    def test_match(self):
        assert isbn_match("978-5-12345-678-9", "ISBN 9785123456789 here").score == 1.0

    def test_no_match(self):
        assert isbn_match("978-5-12345-678-9", "no isbn here").score == 0.0


class TestManualMatch:
    def test_hit(self):
        items = [_item(title="A"), _item(title="B")]
        m = {"foo": 2}
        s = manual_match("foo.pdf", items, m)
        assert s.score == 1.0
        assert "item[1]" in s.detail

    def test_miss(self):
        items = [_item(title="A")]
        s = manual_match("foo.pdf", items, {"bar": 1})
        assert s.score == 0.0


class TestCollectSignals:
    def test_aggregates_for_item(self):
        item = _item(
            authors=["Иванов"], title="Ferroresonance In Power Grids",
            year=2020, doi="10.1109/abc.2020", isbn="",
        )
        text = "Работа Иванова И.И. — ferroresonance in power grids 2020. doi:10.1109/abc.2020"
        signals = collect_signals(text=text, filename="f.pdf", item=item)
        names = {s.name for s in signals}
        assert "author" in names
        assert "title_overlap" in names
        assert "year" in names
        assert "doi" in names
        # Каждый сигнал имеет вес.
        for s in signals:
            assert s.weight > 0
