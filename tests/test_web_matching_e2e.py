"""Браузер различает планируемые имена, созданные копии и ошибки записи."""

import importlib

import pytest
from playwright.sync_api import Page, expect

from tests import test_browser_e2e as browser_fixtures
from tests.test_web_matching import MatchingFixture
from tests.test_web_matching import matching as matching

browser, e2e_server, page = browser_fixtures.browser, browser_fixtures.e2e_server, browser_fixtures.page


@pytest.mark.parametrize("width", [375, 1280])
def test_matching_preview_dry_run_copy_and_failure(
    e2e_server: str,
    page: Page,
    matching: MatchingFixture,
    monkeypatch: pytest.MonkeyPatch,
    width: int,
) -> None:
    _, _, source, output = matching
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/matching")
    page.locator(".matching-settings summary").click()
    page.locator("#source_dir").fill(str(source))
    page.locator("#output_dir").fill(str(output))
    page.locator("#threshold").fill("0.99")
    page.locator("#previewBtn").click()
    expect(page.locator("#resultsSummary")).to_contain_text("совпадений: 1")
    expect(page.locator("#resultsBody")).to_contain_text("✅")
    assert not output.exists()
    page.locator("#dryRun").check()
    expect(page.locator("#runBtn")).to_have_text("Составить отчёт")
    page.locator("#runBtn").click()
    expect(page.locator("#status")).to_contain_text("Предпросмотр завершён")
    expect(page.locator("#resultsBody")).not_to_contain_text("Копия не создана")
    assert not output.exists()
    page.locator("#dryRun").uncheck()
    expect(page.locator("#runBtn")).to_have_text("Копировать с новыми именами")
    page.locator("#runBtn").click()
    expect(page.locator("#status")).to_contain_text("Копирование завершено")
    assert len(list(output.iterdir())) == 1
    original_copy = next(output.iterdir()).read_bytes()

    def fail_copy(*args: object, **kwargs: object) -> None:
        raise PermissionError("Destination is read only")

    module = importlib.import_module("textalchemy.pipeline.match_files")
    monkeypatch.setattr(module.shutil, "copy2", fail_copy)
    page.locator("#runBtn").click()
    expect(page.locator("#resultsBody")).to_contain_text("Копия не создана")
    expect(page.locator("#status")).to_contain_text("копия не создана для 1 файлов")
    expect(page.locator("#status")).to_have_class("status-bar error")
    assert next(output.iterdir()).read_bytes() == original_copy
    assert page.evaluate("window._lastReport.matched[0].copied_path") is None
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.e2e_errors == []


@pytest.mark.parametrize("width", [375, 768, 1280])
@pytest.mark.parametrize("dry_run", [False, True])
def test_collection_report_separates_file_counts_and_saved_matching(
    e2e_server: str, page: Page, matching: MatchingFixture, width: int, dry_run: bool
) -> None:
    from axe_core_python.sync_playwright import Axe

    from tests.test_web_matching import run

    client, _, source, output = matching
    output.mkdir()
    (output / "unrelated.txt").write_text("Unrelated file", encoding="utf-8")
    response = run(client, source, output, dry_run=str(dry_run).lower())
    assert response.json()["success"]
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    mutations = []
    page.on("request", lambda request: mutations.append(request.url) if request.method != "GET" else None)
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/reports")
    expect(page.locator("#status")).to_contain_text("Файлы и записи не изменены")
    expect(page.get_by_role("heading", name="Состояние коллекции")).to_be_visible()
    metrics = page.locator("#stats .metric-card")
    expect(metrics.nth(2)).to_contain_text(str(len(before)))
    expect(metrics.nth(2)).to_contain_text("наличие не подтверждает связь")
    expect(metrics.nth(3).locator("strong")).to_have_text("1")
    expect(page.locator("#lastMatching")).to_contain_text("соответствий")
    details = page.locator("#lastMatching details").first
    assert not details.evaluate("el => el.open")
    details.locator("summary").focus()
    page.keyboard.press("Enter")
    expect(details).to_contain_text("Только план" if dry_run else "Копия создана")
    if dry_run:
        expect(page.locator("#lastMatching")).to_contain_text("Копии не создавались")
    page.locator("#refreshBtn").click()
    expect(page.locator("#refreshBtn")).to_be_enabled()
    assert mutations == []
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
    assert "Готовность" not in page.locator("#stats").inner_text()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not [item for item in Axe().run(page)["violations"] if item.get("impact") in ("serious", "critical")]
    assert page.e2e_errors == []


def test_collection_refresh_failure_keeps_previous_data_and_explains_staleness(
    e2e_server: str, page: Page, matching: MatchingFixture
) -> None:
    page.goto(e2e_server + "/reports")
    expect(page.locator("#status")).to_contain_text("Данные прочитаны")
    before = page.locator("#stats").inner_text()
    page.route("**/api/stats", lambda route: route.fulfill(status=503, json={"detail": "Статистика недоступна"}))
    page.locator("#refreshBtn").click()
    expect(page.locator("#status")).to_contain_text("Показаны предыдущие данные")
    expect(page.locator("#status")).to_have_class("status-bar error")
    assert page.locator("#stats").inner_text() == before
    expect(page.locator("#refreshBtn")).to_be_enabled()
    page.unroute("**/api/stats")
    page.locator("#refreshBtn").click()
    expect(page.locator("#status")).to_contain_text("Данные прочитаны")
    assert page.e2e_errors == ["Failed to load resource: the server responded with a status of 503 (Service Unavailable)"]


@pytest.mark.parametrize("width", [375, 768, 1280])
def test_collection_report_shows_copy_failure_and_unmatched_filename(
    e2e_server: str, page: Page, matching: MatchingFixture, monkeypatch: pytest.MonkeyPatch, width: int
) -> None:
    from tests.test_web_matching import run

    client, _, source, output = matching
    (source / "unknown.txt").write_text("Unknown document", encoding="utf-8")
    original = (source / "Образец.TXT").read_bytes()

    def fail_copy(*args: object, **kwargs: object) -> None:
        raise PermissionError("Read-only destination")

    monkeypatch.setattr("textalchemy.pipeline.match_files.shutil.copy2", fail_copy)
    result = run(client, source, output).json()
    assert not result["success"] and len(result["unmatched"]) == 1
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/reports")
    expect(page.locator("#lastMatching .issue-list")).to_contain_text("Не удалось создать копию")
    details = page.locator("#lastMatching details")
    details.nth(0).locator("summary").click()
    expect(details.nth(0)).to_contain_text("Копия не создана")
    details.nth(1).locator("summary").click()
    expect(details.nth(1)).to_contain_text("unknown.txt")
    assert (source / "Образец.TXT").read_bytes() == original
    assert list(output.iterdir()) == []
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.e2e_errors == []
