"""Bibliography requests must preserve neighbouring records and use atomic imports."""

import ast
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from textalchemy.core.database import Database
from textalchemy.core.types import BibItem
from textalchemy.web.main import app
from textalchemy.web.services.bibliography import BibliographyInput, BibliographyService


@pytest.fixture
def library_db(tmp_path, monkeypatch):
    state = importlib.import_module("textalchemy.web.app")
    database = Database(tmp_path / "library.db")
    monkeypatch.setattr(state, "db", database)
    monkeypatch.setattr(state, "data_dir", tmp_path)
    yield database
    database.engine.dispose()


@pytest.fixture
def bibliography_client(library_db):
    return TestClient(app)


def test_crud_preserves_records_fields_and_response_contract(bibliography_client, library_db):
    neighbour = library_db.add_item(BibItem(title="Neighbour", authors=["N"], url="https://example.invalid", raw_text="Original"))
    created = bibliography_client.post(
        "/api/bibliography",
        data={
            "authors": "  Ada ; ; Grace  ",
            "title": "Notes",
            "year": "2024",
            "source": "notes.pdf",
            "doi": "example",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body == {
        "success": True,
        "item": {
            "id": neighbour.index + 1,
            "authors": ["Ada", "Grace"],
            "title": "Notes",
            "doc_type": "article",
            "year": "2024",
            "journal": "",
            "publisher": "",
            "city": "",
            "pages": "",
            "isbn": "",
            "doi": "example",
            "source": "notes.pdf",
        },
    }
    item_id = body["item"]["id"]
    updated = bibliography_client.put(
        f"/api/bibliography/{item_id}",
        data={
            "authors": "Ada",
            "title": "Changed",
            "year": "",
            "doc_type": "book",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["id"] == item_id
    assert updated.json()["item"]["authors"] == ["Ada"]
    assert updated.json()["item"]["year"] == ""
    assert updated.json()["item"]["doi"] == ""
    records = bibliography_client.get("/api/bibliography").json()
    assert [record["id"] for record in records] == [neighbour.index, item_id]
    assert records[1]["index"] == item_id
    assert records[1]["doc_type"] == "book"
    assert library_db.get_item(neighbour.index) == neighbour
    assert bibliography_client.delete(f"/api/bibliography/{item_id}").json() == {"success": True}
    assert bibliography_client.delete(f"/api/bibliography/{item_id}").json() == {"success": True}
    assert library_db.all_items() == [neighbour]
    missing = bibliography_client.put(f"/api/bibliography/{item_id}", data={"authors": "A", "title": "Missing"})
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Item not found"}


def test_mutations_do_not_scan_or_rewrite_the_collection(library_db, monkeypatch):
    neighbour = library_db.add_item(BibItem(title="Unchanged"))
    service = BibliographyService(library_db)

    def forbidden():
        raise AssertionError("A targeted mutation loaded the entire library")

    monkeypatch.setattr(library_db, "all_items", forbidden)
    created = service.add(BibliographyInput(authors="A", title="New"))["item"]["id"]
    service.update(created, BibliographyInput(authors="B", title="Updated"))
    service.delete(created)
    assert library_db.get_item(neighbour.index) == neighbour


def test_update_keeps_unedited_fields_of_the_selected_record(bibliography_client, library_db):
    existing = library_db.add_item(BibItem(title="Before", url="https://example.invalid/item", raw_text="Provenance"))
    response = bibliography_client.put(f"/api/bibliography/{existing.index}", data={"authors": "A", "title": "After"})
    assert response.status_code == 200
    assert response.json()["item"]["url"] == existing.url
    assert response.json()["item"]["raw_text"] == "Provenance"
    assert library_db.get_item(existing.index).url == existing.url


def test_disappearing_record_returns_not_found_without_resurrection(bibliography_client, library_db, monkeypatch):
    record = library_db.add_item(BibItem(title="Deleted concurrently"))
    original = library_db.update_item

    def disappear(item_id, item):
        library_db.delete_item(item_id)
        return original(item_id, item)

    monkeypatch.setattr(library_db, "update_item", disappear)
    result = bibliography_client.put(f"/api/bibliography/{record.index}", data={"authors": "A", "title": "New"})
    assert result.status_code == 404
    assert library_db.all_items() == []


def test_import_appends_with_database_ids_and_keeps_existing_records(bibliography_client, library_db):
    existing = library_db.add_item(BibItem(index=40, title="Keep"))
    content = "1. Иванов И. И. Анализ данных. 2024.\n2. Петров П. П. Методы. 2023.".encode("utf-8")
    result = bibliography_client.post("/api/bibliography/import", files={"file": ("sources.txt", content, "text/plain")})
    assert result.status_code == 200
    assert result.json() == {"success": True, "count": 2}
    records = library_db.all_items()
    assert records[0] == existing
    assert [record.index for record in records] == [40, 41, 42]
    assert [record.year for record in records[1:]] == [2024, 2023]


def test_failed_import_rolls_back_all_new_records(library_db, tmp_path, monkeypatch):
    existing = library_db.add_item(BibItem(title="Keep"))
    with library_db.engine.begin() as connection:
        connection.execute(
            text("""
            CREATE TRIGGER reject_fixture BEFORE INSERT ON bibliography
            WHEN NEW.title = 'Reject'
            BEGIN SELECT RAISE(ABORT, 'fixture rejection'); END
        """)
        )
    module = importlib.import_module("textalchemy.web.services.bibliography")
    monkeypatch.setattr(
        module.BibliographyParser,
        "parse_file",
        lambda path: [
            BibItem(index=1, title="First"),
            BibItem(index=2, title="Reject"),
        ],
    )
    with pytest.raises(IntegrityError, match="fixture rejection"):
        BibliographyService(library_db).import_file(tmp_path / "source.txt")
    assert library_db.all_items() == [existing]


def test_failed_parse_preserves_library_and_removes_uploaded_workspace(bibliography_client, library_db, monkeypatch):
    existing = library_db.add_item(BibItem(title="Keep"))
    routes = importlib.import_module("textalchemy.web.routes.bibliography")
    service = importlib.import_module("textalchemy.web.services.bibliography")
    workspaces = []
    create = routes.create_web_workspace

    def capture_workspace():
        workspace = create()
        workspaces.append(workspace)
        return workspace

    def fail(path):
        raise ValueError("parser failure")

    monkeypatch.setattr(routes, "create_web_workspace", capture_workspace)
    monkeypatch.setattr(service.BibliographyParser, "parse_file", fail)
    with pytest.raises(ValueError, match="parser failure"):
        bibliography_client.post("/api/bibliography/import", files={"file": ("sources.txt", b"content", "text/plain")})
    assert library_db.all_items() == [existing]
    assert len(workspaces) == 1
    assert not workspaces[0].path.exists()


def test_smart_parse_is_a_preview_without_persistence(bibliography_client, library_db):
    response = bibliography_client.post("/api/bibliography/smart-parse", data={"text": "Иванов И. И. Анализ данных. 2024."})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert len(body["items"]) == 1
    assert set(body["items"][0]) == {"index", "authors", "title", "year"}
    assert body["items"][0]["year"] == 2024
    assert library_db.all_items() == []


def test_bibliography_routes_and_service_keep_their_boundaries():
    source = Path(__file__).parents[1] / "src/textalchemy/web"
    route = source / "routes/bibliography.py"
    tree = ast.parse(route.read_text(encoding="utf-8"))
    assert not any(isinstance(node, (ast.For, ast.ListComp)) for node in ast.walk(tree))
    for name, forbidden in [
        ("routes/bibliography.py", {"textalchemy.organize", "textalchemy.pipeline", "textalchemy.core.database"}),
        ("services/bibliography.py", {"fastapi", "textalchemy.web.app", "sqlalchemy"}),
    ]:
        imports = ast.parse((source / name).read_text(encoding="utf-8"))
        for node in ast.walk(imports):
            modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            assert not any(module == blocked or module.startswith(blocked + ".") for module in modules for blocked in forbidden)
