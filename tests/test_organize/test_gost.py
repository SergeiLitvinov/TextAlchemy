from pathlib import Path

import pytest

from textalchemy.organize.bibliography import BibItem
from textalchemy.organize.gost import GostFormatter


@pytest.fixture
def fmt():
    return GostFormatter()


def make(authors="", title="", year=0, doc_type="article", source="",
         pages="", doi="", isbn=""):
    return BibItem(
        authors=authors,
        title=title,
        year=year,
        doc_type=doc_type,
        source=source,
        pages=pages,
        doi=doi,
        isbn=isbn,
    )


class TestGostFormatter:
    def test_format_article(self, fmt):
        result = fmt.format(make(
            authors=["Иванов И.И."], title="Статья", year=2024,
            source="Журнал", pages="С. 10-20", doi="10.1234/test",
        ))
        assert "Иванов" in result
        assert "Статья" in result
        assert "2024" in result
        assert "//" in result
        assert "С. 10-20" in result
        assert "10.1234" in result

    def test_format_article_minimal(self, fmt):
        result = fmt.format(make(title="Статья"))
        assert result == " Статья"

    def test_format_book(self, fmt):
        result = fmt.format(make(
            authors=["Петров П.П."], title="Учебник", year=2023,
            pages="200", isbn="978-5-1234-5678-9", doc_type="book",
        ))
        assert "Учебник" in result
        assert "200 с." in result
        assert "ISBN" in result

    def test_format_book_no_year(self, fmt):
        result = fmt.format(make(
            authors=["Автор"], title="Книга", pages="100", doc_type="book",
        ))
        assert "100 с." in result

    def test_format_dissertation(self, fmt):
        result = fmt.format(make(
            authors=["Сидоров С.С."], title="Диссертация", year=2024,
            pages="150", doc_type="dissertation",
        ))
        assert "дис." in result
        assert "150 с." in result

    def test_format_dissertation_no_year(self, fmt):
        result = fmt.format(make(
            authors=["Автор"], title="Дисс", doc_type="dissertation",
        ))
        assert "дис." not in result

    def test_format_monograph(self, fmt):
        result = fmt.format(make(
            authors=["Автор"], title="Монография", year=2022,
            pages="300", isbn="978-5-0000-0000-0", doc_type="monograph",
        ))
        assert "300 с." in result
        assert "ISBN" in result

    def test_format_conference(self, fmt):
        result = fmt.format(make(
            authors=["Автор"], title="Доклад", year=2024,
            source="Материалы конф.", pages="С. 5-10",
            doi="10.9999/test", doc_type="conference",
        ))
        assert "Автор" in result
        assert "Материалы" in result
        assert "С. 5-10" in result
        assert "10.9999" in result

    def test_format_patent(self, fmt):
        result = fmt.format(make(
            authors=["Изобретатель"], title="Патент", year=2023, doc_type="patent",
        ))
        assert "Изобретатель" in result
        assert "Патент" in result
        assert "2023" in result

    def test_format_patent_no_authors(self, fmt):
        result = fmt.format(make(title="Патент", year=2023, doc_type="patent"))
        assert "Патент" in result
        assert "2023" in result

    def test_format_standard(self, fmt):
        result = fmt.format(make(title="ГОСТ Р 12345", year=2020, doc_type="standard"))
        assert "ГОСТ" in result
        assert "2020" in result

    def test_format_abstract(self, fmt):
        result = fmt.format(make(
            authors=["Автор"], title="Автореферат", year=2024,
            pages="25", doc_type="abstract",
        ))
        assert "25 с." in result

    def test_format_report(self, fmt):
        result = fmt.format(make(
            authors=["Автор"], title="Отчёт", year=2024, doc_type="report",
        ))
        assert "Отчёт" in result
        assert "2024" in result

    def test_format_collection(self, fmt):
        result = fmt.format(make(title="Сборник", year=2024, doc_type="collection"))
        assert "Сборник" in result
        assert "2024" in result

    def test_format_collection_no_year(self, fmt):
        result = fmt.format(make(title="Сборник", doc_type="collection"))
        assert result == "Сборник"

    def test_format_unknown_type_defaults_to_article(self, fmt):
        result = fmt.format(make(title="Что-то", doc_type="unknown"))
        assert result == " Что-то"

    def test_format_fa_string_authors(self, fmt):
        result = fmt.format(make(authors="Строка", title="Тест"))
        assert "Строка" in result

    def test_format_bibliography(self, fmt):
        items = [
            BibItem(index=1, authors=["А"], title="Работа 1", year=2024, doc_type="article"),
            BibItem(index=2, authors=["Б"], title="Работа 2", year=2023, doc_type="article"),
        ]
        result = fmt.format_bibliography(items)
        assert result.startswith("1.")
        assert "2." in result

    def test_convert_file(self, tmp_path, fmt):
        src = tmp_path / "input.txt"
        src.write_text("1. Автор А.А. Работа // Журнал. 2024.", encoding="utf-8")
        dst = tmp_path / "output.txt"
        fmt.convert_file(str(src), str(dst))
        assert dst.exists()
        content = dst.read_text(encoding="utf-8")
        assert content.startswith("1.")
        assert "2024" in content
