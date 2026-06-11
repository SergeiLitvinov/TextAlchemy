"""Тесты pipeline: ingest, extract, match."""
from __future__ import annotations

from pathlib import Path

import pytest

from textalchemy.core.registry import all_operations
from textalchemy.core.types import BibItem, DocFormat, Document

# Прямые импорты — декоратор @operation регистрирует их в реестре.
from textalchemy.pipeline.extract import extract_text  # noqa: F401
from textalchemy.pipeline.ingest import ingest_file  # noqa: F401
from textalchemy.pipeline.match import match_bibliography  # noqa: F401


def test_ingest_registers():
    assert any(s.id == "ingest.file" for s in all_operations())


def test_extract_registers():
    assert any(s.id == "extract.text" for s in all_operations())


def test_match_registers():
    assert any(s.id == "match.bibliography" for s in all_operations())


def test_ingest_txt(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello world", encoding="utf-8")
    doc = ingest_file(path=f)
    assert doc.format == DocFormat.TXT
    assert doc.size == len("hello world")
    assert len(doc.sha256) == 64


def test_ingest_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        ingest_file(path=tmp_path / "nope.txt")


def test_extract_txt(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    doc = ingest_file(path=f)
    text = extract_text(doc=doc)
    assert text.plain == "hello"
    assert text.source_format == DocFormat.TXT


def test_extract_docx(tmp_path):
    from docx import Document

    f = tmp_path / "a.docx"
    d = Document()
    d.add_paragraph("first paragraph")
    d.add_paragraph("second paragraph")
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "A1"
    table.cell(1, 1).text = "B2"
    d.save(str(f))

    doc = ingest_file(path=f)
    text = extract_text(doc=doc)
    assert "first paragraph" in text.plain
    assert "second paragraph" in text.plain
    assert len(text.tables) == 1
    assert text.tables[0].rows[0][0] == "A1"
    assert text.tables[0].rows[1][1] == "B2"


def test_extract_pdf_chain(tmp_path):
    """Создаём простой PDF и проверяем, что цепочка движков что-то достаёт."""
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")

    f = tmp_path / "a.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello PDF world")
    page.insert_text((72, 100), "Second line here")
    doc.save(str(f))
    doc.close()

    d = ingest_file(path=f)
    text = extract_text(doc=d)
    # Цепочка: pdfplumber → pypdf → pymupdf. Любой движок должен справиться.
    assert "Hello" in text.plain or text.warnings, text.warnings
    assert text.pages >= 1


def _item(**kw):
    base = dict(
        index=1, raw_text="x", authors=[], title="", year=None,
        doc_type="unknown", source="", pages="", doi="", isbn="", url="",
    )
    base.update(kw)
    return BibItem(**base)


def test_match_picks_correct_item():
    from textalchemy.core.types import Text

    f = Path("/dummy.pdf")
    doc = Document(path=f, format=DocFormat.PDF, size=0, sha256="")
    text = Text(
        plain="Работа Иванова И.И. — ferroresonance in power grids 2020. doi:10.1109/abc.2020"
    )
    items = [
        _item(index=1, title="Unrelated Topic", authors=["Sidorov"]),
        _item(index=2, title="Ferroresonance In Power Grids",
              authors=["Иванов"], year=2020, doi="10.1109/abc.2020"),
        _item(index=3, title="Another Paper", authors=["Petrov"]),
    ]
    m = match_bibliography(text=text, document=doc, items=items)
    assert m.matched
    assert m.item is not None
    assert m.item.index == 2


def test_match_below_threshold():
    from textalchemy.core.types import Text

    f = Path("/dummy.pdf")
    doc = Document(path=f, format=DocFormat.PDF, size=0, sha256="")
    text = Text(plain="random unrelated content xyz123")
    items = [_item(index=1, title="Ferroresonance In Power Grids", authors=["Иванов"])]
    m = match_bibliography(text=text, document=doc, items=items, threshold=0.30)
    assert m.matched is False
    assert m.item is None
    # item всё равно сохраняется как «лучший кандидат», но matched=False
    assert m.score < 0.30


def test_match_manual_override():
    from textalchemy.core.types import Text

    f = Path("/foo.pdf")
    doc = Document(path=f, format=DocFormat.PDF, size=0, sha256="")
    text = Text(plain="random content unrelated to anything")
    items = [
        _item(index=1, title="Title A", authors=["A"]),
        _item(index=2, title="Title B", authors=["B"]),
    ]
    m = match_bibliography(text=text, document=doc, items=items, manual={"foo": 1})
    assert m.matched
    assert m.item.index == 1
    assert any(s.name == "manual" for s in m.signals)
