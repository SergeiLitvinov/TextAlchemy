"""Bibliography CRUD and import through the actual Web interface."""

import pytest
from axe_core_python.sync_playwright import Axe
from playwright.sync_api import expect

from tests import test_browser_e2e as browser_fixtures
from tests.test_web_bibliography import library_db as library_db
from textalchemy.core.types import BibItem

browser, e2e_server, page = browser_fixtures.browser, browser_fixtures.e2e_server, browser_fixtures.page


@pytest.mark.parametrize("width", [375, 768, 1280])
def test_library_import_edit_reload_and_delete_preserve_neighbours(e2e_server, page, library_db, tmp_path, width):
    original = library_db.add_item(BibItem(title="Existing source", authors=["Existing author"]))
    source = tmp_path / "sources.txt"
    source.write_text("1. Иванов И. И. Анализ данных. 2024.\n2. Петров П. П. Методы. 2023.", encoding="utf-8")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/bibliography")
    expect(page.locator("#bibCount")).to_have_text("1")
    page.locator("#importPanel > summary").click()
    page.locator("#importFile").set_input_files(source)
    page.locator("#importBtn").click()
    expect(page.locator("#bibCount")).to_have_text("3")
    expect(page.locator("#bibBody tr")).to_have_count(3)
    page.locator("#newItemBtn").click()
    page.locator("#title").fill("Manual source")
    page.locator("#authors").fill("Ada ; Grace")
    page.locator("#year").fill("2024")
    page.locator("#saveBtn").click()
    expect(page.locator("#bibCount")).to_have_text("4")
    row = page.locator("#bibBody tr").filter(has_text="Manual source")
    row.get_by_role("button", name="Редактировать Manual source", exact=True).click()
    expect(page.locator("#authors")).to_have_value("Ada; Grace")
    page.locator("#title").fill("Updated source")
    page.locator("#saveBtn").click()
    expect(page.locator("#bibBody tr").filter(has_text="Updated source")).to_have_count(1)
    page.reload()
    expect(page.locator("#bibCount")).to_have_text("4")
    expect(page.locator("#bibBody tr").filter(has_text="Updated source")).to_have_count(1)
    expect(page.locator("#bibBody tr").filter(has_text="Existing source")).to_have_count(1)
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#bibBody tr").filter(has_text="Updated source").get_by_role("button", name="Удалить Updated source").click()
    expect(page.locator("#bibCount")).to_have_text("3")
    assert library_db.get_item(original.index) == original
    assert [item.title for item in library_db.all_items()][0] == "Existing source"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    violations = [
        violation["id"] for violation in Axe().run(page)["violations"] if violation.get("impact") in {"serious", "critical"}
    ]
    assert not violations, violations
    assert page.e2e_errors == []


@pytest.mark.parametrize("width", [375, 768, 1280])
def test_library_year_search_and_cancelled_editor_switch_preserve_draft(e2e_server, page, library_db, width):
    library_db.add_item(BibItem(title="First source", authors=["Ada"], year="2024", doc_type="book"))
    library_db.add_item(BibItem(title="Second source", authors=["Grace"], year="2023"))
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/bibliography")
    expect(page.locator("#bibEditor")).to_be_hidden()
    requests = []
    page.on("request", lambda request: requests.append(request.url) if "/api/bibliography" in request.url else None)
    page.locator("#bibSearch").fill("2024")
    expect(page.locator("#bibBody tr")).to_have_count(1)
    expect(page.locator("#bibShown")).to_have_text("Показано: 1")
    expect(page.locator("#bibBody")).to_contain_text("Книга")
    page.locator("#bibSearch").fill("missing")
    expect(page.locator("#bibEmpty")).to_contain_text("По этому запросу ничего не найдено")
    page.locator("#bibSearch").fill("")
    page.get_by_role("button", name="Редактировать First source", exact=True).click()
    expect(page.locator("#title")).to_be_focused()
    assert not page.locator("#sourceDetails").evaluate("el => el.open")
    page.locator("#title").fill("Unsaved title")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator("#newItemBtn").click()
    expect(page.locator("#title")).to_have_value("Unsaved title")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Редактировать Second source", exact=True).click()
    expect(page.locator("#title")).to_have_value("Unsaved title")
    assert requests == []
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#cancelEdit").click()
    expect(page.locator("#bibEditor")).to_be_hidden()
    assert [item.title for item in library_db.all_items()] == ["First source", "Second source"]
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.e2e_errors == []


@pytest.mark.parametrize("width", [375, 768, 1280])
def test_library_save_failure_keeps_draft_and_freezes_mutations(e2e_server, page, library_db, width):
    held = []
    page.route("**/api/bibliography", lambda route: held.append(route))
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/bibliography")
    page.locator("#newItemBtn").click()
    page.locator("#title").fill("Retained draft")
    page.locator("#authors").fill("Ada")
    with page.expect_request("**/api/bibliography"):
        page.locator("#saveBtn").click()
    expect(page.locator("#title")).to_be_disabled()
    expect(page.locator("#newItemBtn")).to_be_disabled()
    expect(page.locator("#cancelEdit")).to_be_disabled()
    assert len(held) == 1
    held[0].fulfill(status=503, json={"detail": "Хранилище недоступно"})
    expect(page.locator("#libraryStatus")).to_contain_text("Введённые данные сохранены в карточке")
    expect(page.locator("#title")).to_have_value("Retained draft")
    expect(page.locator("#saveBtn")).to_be_enabled()
    assert library_db.all_items() == []
    page.unroute("**/api/bibliography")
    page.locator("#saveBtn").click()
    expect(page.locator("#bibCount")).to_have_text("1")
    assert library_db.all_items()[0].title == "Retained draft"
    assert page.e2e_errors == ["Failed to load resource: the server responded with a status of 503 (Service Unavailable)"]


def test_import_success_with_failed_refresh_does_not_offer_duplicate_import(e2e_server, page, library_db):
    page.goto(e2e_server + "/bibliography")
    page.locator("#importPanel > summary").click()
    expect(page.locator("#importBtn")).to_be_disabled()
    page.locator("#importFile").set_input_files(
        {
            "name": "sources.txt",
            "mimeType": "text/plain",
            "buffer": "Иванов И. И. Анализ данных. 2024.".encode(),
        }
    )
    expect(page.locator("#importSelection")).to_contain_text("sources.txt")
    page.route("**/api/bibliography", lambda route: route.fulfill(status=503, json={"detail": "Список недоступен"}))
    page.locator("#importBtn").click()
    expect(page.locator("#libraryStatus")).to_contain_text("Повторный импорт не требуется")
    expect(page.locator("#importBtn")).to_be_disabled()
    expect(page.locator("#importSelection")).to_have_text("Файл не выбран.")
    assert len(library_db.all_items()) == 1
    page.unroute("**/api/bibliography")
    page.locator("#refreshLibraryBtn").click()
    expect(page.locator("#bibCount")).to_have_text("1")
    assert len(library_db.all_items()) == 1
    assert page.e2e_errors == ["Failed to load resource: the server responded with a status of 503 (Service Unavailable)"]
