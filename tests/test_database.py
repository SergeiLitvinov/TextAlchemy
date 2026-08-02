import json
import tempfile
from pathlib import Path

import pytest

from textalchemy.core.database import BibRecord, Database
from textalchemy.organize.bibliography import BibItem


@pytest.fixture
def db(tmp_path):
    database = Database(db_path=str(tmp_path / "test.db"))
    yield database
    database.engine.dispose()


@pytest.fixture
def sample_item():
    return BibItem(
        index=0,
        raw_text="Иванов И.И. Название работы // Журнал. 2024. № 1. С. 10-20.",
        authors=["Иванов", "Петров"],
        title="Название работы",
        year=2024,
        doc_type="article",
        source="Журнал",
        pages="10-20",
        doi="10.1000/test",
        isbn="978-5-0000-0000-0",
        url="https://example.com",
    )


class TestBibRecord:
    def test_to_bibitem(self):
        record = BibRecord(
            id=1,
            authors=json.dumps(["Иванов", "Петров"], ensure_ascii=False),
            title="Test Title",
            year=2024,
            doc_type="article",
            source="Journal",
            pages="10-20",
            doi="10.1000/test",
            isbn="978-5-0000-0000-0",
            url="https://example.com",
            raw_text="Some raw text",
        )
        item = record.to_bibitem()
        assert item.index == 1
        assert item.authors == ["Иванов", "Петров"]
        assert item.title == "Test Title"
        assert item.year == 2024
        assert item.doc_type == "article"
        assert item.source == "Journal"
        assert item.pages == "10-20"
        assert item.doi == "10.1000/test"
        assert item.isbn == "978-5-0000-0000-0"
        assert item.url == "https://example.com"
        assert item.raw_text == "Some raw text"

    def test_to_bibitem_empty_authors(self):
        record = BibRecord(id=2, authors="[]", title="Title")
        item = record.to_bibitem()
        assert item.authors == []
        assert item.title == "Title"

    def test_to_bibitem_none_authors(self):
        record = BibRecord(id=3, authors=None, title="Title")
        item = record.to_bibitem()
        assert item.authors == []

    def test_from_bibitem(self, sample_item):
        record = BibRecord.from_bibitem(sample_item, record_id=5)
        assert record.id == 5
        assert json.loads(record.authors) == ["Иванов", "Петров"]
        assert record.title == "Название работы"
        assert record.year == 2024
        assert record.doc_type == "article"
        assert record.source == "Журнал"
        assert record.pages == "10-20"
        assert record.doi == "10.1000/test"
        assert record.isbn == "978-5-0000-0000-0"
        assert record.url == "https://example.com"
        assert record.raw_text == sample_item.raw_text

    def test_from_bibitem_no_id(self, sample_item):
        record = BibRecord.from_bibitem(sample_item)
        assert record.id is None  # autoincrement


class TestDatabase:
    def test_init_creates_db_file(self, db, tmp_path):
        assert (tmp_path / "test.db").exists()

    def test_init_creates_tables(self, db):
        """Tables should be created; querying all should not error."""
        items = db.all_items()
        assert items == []

    def test_add_item(self, db, sample_item):
        result = db.add_item(sample_item)
        assert result.index is not None
        assert result.index > 0

    def test_add_and_get_item(self, db, sample_item):
        added = db.add_item(sample_item)
        retrieved = db.get_item(added.index)
        assert retrieved is not None
        assert retrieved.title == "Название работы"
        assert retrieved.authors == ["Иванов", "Петров"]
        assert retrieved.year == 2024

    def test_get_item_not_found(self, db):
        assert db.get_item(999) is None

    def test_all_items(self, db, sample_item):
        db.add_item(sample_item)
        item2 = BibItem(authors=["Петров"], title="Вторая работа", year=2023, doc_type="book")
        db.add_item(item2)
        items = db.all_items()
        assert len(items) == 2
        assert items[0].title == "Название работы"
        assert items[1].title == "Вторая работа"

    def test_all_items_empty(self, db):
        assert db.all_items() == []

    def test_update_item(self, db, sample_item):
        added = db.add_item(sample_item)
        updated = BibItem(
            authors=["Сидоров"],
            title="Обновлённая работа",
            year=2025,
            doc_type="book",
            source="Новое издательство",
            pages="100-200",
            doi="10.2000/updated",
            isbn="978-5-1111-1111-1",
            url="https://updated.com",
            journal="Новый журнал",
            publisher="Новое издательство",
            city="Москва",
            raw_text="Updated raw text",
        )
        success = db.update_item(added.index, updated)
        assert success is True

        retrieved = db.get_item(added.index)
        assert retrieved is not None
        assert retrieved.authors == ["Сидоров"]
        assert retrieved.title == "Обновлённая работа"
        assert retrieved.year == 2025
        assert retrieved.doc_type == "book"
        assert retrieved.journal == "Новый журнал"
        assert retrieved.publisher == "Новое издательство"
        assert retrieved.city == "Москва"

    def test_update_item_not_found(self, db, sample_item):
        success = db.update_item(999, sample_item)
        assert success is False

    def test_delete_item(self, db, sample_item):
        added = db.add_item(sample_item)
        success = db.delete_item(added.index)
        assert success is True
        assert db.get_item(added.index) is None

    def test_delete_item_not_found(self, db):
        success = db.delete_item(999)
        assert success is False

    def test_delete_then_add_again(self, db, sample_item):
        added = db.add_item(sample_item)
        idx = added.index
        db.delete_item(idx)
        added2 = db.add_item(sample_item)
        assert added2.index is not None
        assert db.get_item(added2.index) is not None

    def test_import_from_file(self, db):
        text = "1. Тестов Т.Т. Тестовая работа. М.: Издательство, 2023. 100 с."
        path = Path(tempfile.mktemp(suffix=".txt"))
        try:
            path.write_text(text, encoding="utf-8")
            count = db.import_from_file(str(path))
            assert count == 1
            items = db.all_items()
            assert len(items) == 1
        finally:
            path.unlink(missing_ok=True)

    def test_import_from_file_missing(self, db):
        count = db.import_from_file("nonexistent.txt")
        assert count == 0

    def test_add_item_preserves_all_fields(self, db):
        item = BibItem(
            raw_text="Test",
            authors=["Author1"],
            title="Full Title",
            year=2022,
            doc_type="monograph",
            source="Publisher",
            pages="1-300",
            doi="10.1234/test",
            isbn="978-5-9999-9999-9",
            url="https://test.com",
        )
        added = db.add_item(item)
        retrieved = db.get_item(added.index)
        assert retrieved is not None
        assert retrieved.raw_text == "Test"
        assert retrieved.authors == ["Author1"]
        assert retrieved.title == "Full Title"
        assert retrieved.year == 2022
        assert retrieved.doc_type == "monograph"
        assert retrieved.source == "Publisher"
        assert retrieved.pages == "1-300"
        assert retrieved.doi == "10.1234/test"
        assert retrieved.isbn == "978-5-9999-9999-9"
        assert retrieved.url == "https://test.com"

    def test_custom_db_path(self, tmp_path):
        custom_path = tmp_path / "custom" / "mydb.sqlite"
        db = Database(db_path=str(custom_path))
        assert custom_path.exists()
        db.add_item(BibItem(title="Test"))
        assert len(db.all_items()) == 1
