"""Тесты core.types."""
from __future__ import annotations

from pathlib import Path

import pytest

from textalchemy.core.types import (
    Block,
    BlockType,
    DocFormat,
    Document,
    Match,
    Signal,
    Text,
)


class TestDocument:
    def test_from_path_detects_pdf(self, tmp_path):
        f = tmp_path / "a.pdf"
        f.write_bytes(b"%PDF-1.4")
        doc = Document.from_path(f)
        assert doc.format == DocFormat.PDF
        assert doc.size > 0

    def test_from_path_unknown(self, tmp_path):
        f = tmp_path / "x.bin"
        f.write_bytes(b"\x00")
        doc = Document.from_path(f)
        assert doc.format == DocFormat.UNKNOWN

    def test_from_path_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Document.from_path(tmp_path / "nope.pdf")


class TestText:
    def test_empty_is_falsy(self):
        assert bool(Text()) is False

    def test_with_plain_is_truthy(self):
        assert bool(Text(plain="x")) is True

    def test_blocks_and_plain_independent(self):
        t = Text(blocks=[Block(type=BlockType.PARAGRAPH, text="hi")], plain="hi")
        assert len(t.blocks) == 1
        assert t.plain == "hi"


class TestSignal:
    def test_contribution(self):
        s = Signal(name="x", score=2.0, weight=3.0)
        assert s.contribution == 6.0

    def test_default_weight(self):
        assert Signal(name="x", score=1.0).contribution == 1.0


class TestMatch:
    def test_score_sums_signals(self):
        doc = Document(path=Path("/x"), format=DocFormat.UNKNOWN, size=0, sha256="")
        m = Match(
            document=doc,
            item=None,
            signals=[
                Signal(name="a", score=1.0, weight=2.0),
                Signal(name="b", score=0.5, weight=1.0),
            ],
        )
        assert m.score == pytest.approx(2.5)

    def test_signal_score_lookup(self):
        doc = Document(path=Path("/x"), format=DocFormat.UNKNOWN, size=0, sha256="")
        m = Match(
            document=doc,
            item=None,
            signals=[Signal(name="author", score=1.0, weight=1.5)],
        )
        assert m.signal_score("author") == pytest.approx(1.5)
        assert m.signal_score("missing") == 0.0
