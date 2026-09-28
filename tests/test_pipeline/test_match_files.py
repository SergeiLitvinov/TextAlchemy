"""Тесты pipeline.match_files и pipeline.bibliography."""
from __future__ import annotations

from pathlib import Path

import pytest

from textalchemy.core.types import BibItem
from textalchemy.pipeline import bibliography as _bib_op  # noqa: F401
from textalchemy.pipeline import match_files as _match_files_op  # noqa: F401
from textalchemy.pipeline.match_files import match_files


def _write_bib(tmp_path: Path) -> Path:
    bib = tmp_path / "bib.txt"
    bib.write_text(
        "1. Иванов И.И. Ferroresonance in Power Grids. Электричество. 2020. с. 10-20.\n"
        "2. Smith J. Quantum Computing. 2019.\n"
        "3. Петров П.П. Other Topic. 2018.\n",
        encoding="utf-8",
    )
    return bib


def _item(**kw) -> BibItem:
    base = dict(
        index=1, raw_text="x", authors=[], title="", year=None,
        doc_type="unknown", source="", pages="", doi="", isbn="", url="",
    )
    base.update(kw)
    return BibItem(**base)


class TestMatchFilesRegistry:
    def test_registered(self):
        from textalchemy.core.registry import all_operations
        ids = {s.id for s in all_operations()}
        assert "match.files" in ids
        assert "bibliography.parse" in ids
        assert "bibliography.smart_parse" in ids


class TestMatchFiles:
    def test_finds_matching_txt(self, tmp_path):
        bib = _write_bib(tmp_path)
        from textalchemy.pipeline.bibliography import parse_bibliography
        items = parse_bibliography(path=bib)

        src = tmp_path / "src"
        src.mkdir()
        # Имя файла содержит ключевые слова из bib
        (src / "Ferroresonance_in_Power_Grids_2020.txt").write_text(
            "Работа Иванова И.И. — ferroresonance in power grids 2020",
            encoding="utf-8",
        )
        # И нерелевантный
        (src / "unrelated.txt").write_text("completely unrelated", encoding="utf-8")

        out = tmp_path / "out"
        matches = match_files(
            source=src, items=items, threshold=0.30,
            output_dir=out, copy=True,
        )
        assert len(matches) == 2
        matched = [m for m in matches if m.matched]
        assert len(matched) == 1
        # Лучший матч — на Иванов/ferroresonance
        assert matched[0].item is not None
        assert matched[0].item.index == 1
        # Файл скопирован с новым именем
        copied = list(out.iterdir())
        assert len(copied) == 1
        assert matched[0].copied_path == copied[0]
        assert all(m.copied_path is None for m in matches if not m.matched)
        assert "Иванов" in copied[0].name or "ivanov" in copied[0].name.lower()

    def test_no_files(self, tmp_path):
        bib = _write_bib(tmp_path)
        from textalchemy.pipeline.bibliography import parse_bibliography
        items = parse_bibliography(path=bib)

        src = tmp_path / "empty"
        src.mkdir()
        matches = match_files(source=src, items=items)
        assert matches == []

    def test_source_not_dir(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            match_files(source=tmp_path / "nope", items=[])

    def test_skip_extension(self, tmp_path):
        from textalchemy.pipeline.bibliography import parse_bibliography
        items = parse_bibliography(path=_write_bib(tmp_path))
        src = tmp_path / "src"
        src.mkdir()
        # .bin — не в ext_map по умолчанию
        (src / "data.bin").write_text("Ferroresonance in Power Grids 2020 Иванов", encoding="utf-8")
        matches = match_files(source=src, items=items)
        assert matches == []  # .bin не сканируется

    def test_no_output_dir_no_copy(self, tmp_path):
        """Без output_dir — матчинг происходит, но копирования нет."""
        from textalchemy.pipeline.bibliography import parse_bibliography
        items = parse_bibliography(path=_write_bib(tmp_path))
        src = tmp_path / "src"
        src.mkdir()
        (src / "Ferroresonance_2020.txt").write_text("Иванов 2020", encoding="utf-8")
        matches = match_files(source=src, items=items, output_dir=None, copy=False)
        assert len(matches) == 1
        assert matches[0].copied_path is None
        # Только src и bib.txt (без out/)
        assert {p.name for p in tmp_path.iterdir()} == {"src", "bib.txt"}


class TestBibliographyParse:
    def test_parse(self, tmp_path):
        from textalchemy.pipeline.bibliography import parse_bibliography
        bib = _write_bib(tmp_path)
        items = parse_bibliography(path=bib)
        assert len(items) == 3
        assert items[0].title  # non-empty
        assert items[0].year == 2020
        assert items[1].authors  # non-empty

    def test_missing(self, tmp_path):
        from textalchemy.pipeline.bibliography import parse_bibliography
        with pytest.raises(FileNotFoundError):
            parse_bibliography(path=tmp_path / "nope.txt")

    def test_smart_parse(self):
        from textalchemy.pipeline.bibliography import smart_parse_bibliography
        text = (
            "1. Иванов И.И. Title one. Source. 2020. с. 10.\n"
            "2. Smith J. Title two. 2019.\n"
            "3. Петров П.П. Other. 2018.\n"
        )
        items = smart_parse_bibliography(text=text)
        assert len(items) == 3
        assert items[0].year == 2020
        assert "Иванов" in items[0].authors[0]
