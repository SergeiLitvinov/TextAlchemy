"""Приёмка конструктора: реальные файлы, актуальность проверок и сохранение текста."""

import re

import pytest
from axe_core_python.sync_playwright import Axe
from playwright.sync_api import expect

from tests import test_browser_e2e as fixtures

browser, page, e2e_server, task_store = fixtures.browser, fixtures.page, fixtures.e2e_server, fixtures.task_store


@pytest.mark.parametrize("width", [375, 768, 1280])
@pytest.mark.parametrize("expert", [False, True])
def test_pipeline_upload_validate_run_download_and_result_revision(e2e_server, page, task_store, tmp_path, width, expert):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/pipeline")
    expect(page.locator("#stepsList .step-card")).to_have_count(3)
    assert not page.locator("#operationCatalog").evaluate("el => el.open")
    expect(page.locator("#p-0-path")).to_have_value("")
    page.locator("#p-0-path-file").set_input_files(
        {
            "name": "source.txt",
            "mimeType": "text/plain",
            "buffer": b"Pipeline original text",
        }
    )
    expect(page.locator("[data-upload-status]")).to_contain_text("source.txt загружен")
    page.locator("#validateBtn").click()
    expect(page.locator("#status")).to_contain_text("Связи в порядке")
    expect(page.locator("#status")).to_contain_text("Сценарий не выполнялся")
    expect(page.locator("#pipeline-result")).to_be_hidden()
    page.locator("#stepsList .step-card").nth(2).locator(".step-extra > summary").click()
    page.locator("#p-2-title").fill("2024")
    expect(page.locator("#status")).to_contain_text("Сценарий изменён")
    if expert:
        page.locator("#modeExpertBtn").click()
        expect(page.locator("#expertMode")).to_be_visible()
        expect(page.locator("#expertRunBtn")).to_be_enabled()
    page.locator("#expertRunBtn" if expert else "#runBtn").click()
    expect(page.locator("#pipeline-result-title")).to_have_text("Сценарий выполнен", timeout=60000)
    expect(page.locator("#resultValue")).to_contain_text(r"\title{2024}")
    expect(page.locator("#resultValue")).to_contain_text("Pipeline original text")
    with page.expect_download() as download:
        page.locator("#resultDownloads a").click()
    result = tmp_path / download.value.suggested_filename
    download.value.save_as(result)
    assert result.suffix == ".tex"
    assert "Pipeline original text" in result.read_text(encoding="utf-8")
    if expert:
        value = page.locator("#specText").input_value()
        page.locator("#specText").fill(value.replace("2024", "2025"))
    else:
        page.locator("#p-2-title").fill("2025")
    expect(page.locator("#resultVersionNote")).to_contain_text("предыдущего запуска")
    expect(page.locator("#resultValue")).to_contain_text(r"\title{2024}")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not [item for item in Axe().run(page)["violations"] if item.get("impact") in ("serious", "critical")]
    assert page.e2e_errors == []


def test_pipeline_invalid_expert_text_keeps_text_and_previous_builder(e2e_server, page):
    page.goto(e2e_server + "/pipeline")
    expect(page.locator("#stepsList .step-card")).to_have_count(3)
    page.locator("#modeExpertBtn").click()
    expect(page.locator("#expertRunBtn")).to_be_enabled()
    invalid = "steps: [ broken"
    page.locator("#specText").fill(invalid)
    page.locator("#modeVisualBtn").click()
    expect(page.locator("#statusExpert")).to_contain_text("Текст сохранён")
    expect(page.locator("#specText")).to_have_value(invalid)
    expect(page.locator("#expertMode")).to_be_visible()
    assert page.locator("#stepsList .step-card").count() == 3
    page.locator("#specText").fill('{"steps": [{"op": "missing.operation", "output": "value"}]}')
    page.locator("#modeVisualBtn").click()
    expect(page.locator("#visualMode")).to_be_visible()
    expect(page.locator(".op-select")).to_have_value("missing.operation")
    expect(page.locator(".op-select")).to_contain_text("Недоступное действие")
    page.locator("#validateBtn").click()
    expect(page.locator("#status")).to_contain_text("Найдены ошибки")
    assert page.e2e_errors == []


@pytest.mark.parametrize("action", ["validate", "run", "yaml", "parse"])
def test_pipeline_pending_requests_lock_edits_and_release_after_failure(e2e_server, page, action):
    page.goto(e2e_server + "/pipeline")
    expect(page.locator("#stepsList .step-card")).to_have_count(3)
    if action == "parse":
        page.locator("#modeExpertBtn").click()
        expect(page.locator("#expertRunBtn")).to_be_enabled()
    held = []
    page.route("**/api/pipeline/" + action, lambda route: held.append(route))
    button = {"validate": "#validateBtn", "run": "#runBtn", "yaml": "#modeExpertBtn", "parse": "#modeVisualBtn"}[action]
    with page.expect_request("**/api/pipeline/" + action):
        page.locator(button).click()
    expect(page.locator("#modeVisualBtn")).to_be_disabled()
    expect(page.locator("#modeExpertBtn")).to_be_disabled()
    expect(page.locator("#runBtn")).to_be_disabled()
    expect(page.locator("#p-0-path")).to_be_disabled()
    assert len(held) == 1
    held[0].fulfill(status=503, json={"detail": "Временно недоступно"})
    expect(page.locator("#modeVisualBtn")).to_be_enabled()
    expect(page.locator("#modeExpertBtn")).to_be_enabled()
    if action == "yaml":
        expect(page.locator("#specText")).to_have_value(re.compile('"ingest.file"'))
        expect(page.locator("#statusExpert")).to_contain_text("перенесены в JSON")
    if action == "parse":
        expect(page.locator("#expertMode")).to_be_visible()
        expect(page.locator("#statusExpert")).to_contain_text("Текст сохранён")
    assert page.e2e_errors == ["Failed to load resource: the server responded with a status of 503 (Service Unavailable)"]


def test_pipeline_file_upload_failure_preserves_selection_and_can_retry(e2e_server, page, task_store):
    page.goto(e2e_server + "/pipeline")
    expect(page.locator("#stepsList .step-card")).to_have_count(3)
    held = []
    page.route("**/api/pipeline/files", lambda route: held.append(route))
    with page.expect_request("**/api/pipeline/files"):
        page.locator("#p-0-path-file").set_input_files({"name": "retry.txt", "mimeType": "text/plain", "buffer": b"Retry input"})
    expect(page.locator("#runBtn")).to_be_disabled()
    expect(page.locator("#modeExpertBtn")).to_be_disabled()
    held[0].fulfill(status=503, json={"detail": "Загрузка недоступна"})
    expect(page.locator("[data-upload-status]")).to_contain_text("Текущий путь шага не изменён")
    expect(page.locator("#p-0-path")).to_have_value("")
    assert page.locator("#p-0-path-file").evaluate("el => el.files[0].name") == "retry.txt"
    expect(page.locator("[data-retry-upload]")).to_be_visible()
    page.unroute("**/api/pipeline/files")
    page.locator("[data-retry-upload]").click()
    expect(page.locator("[data-upload-status]")).to_contain_text("retry.txt загружен")
    expect(page.locator("[data-retry-upload]")).to_be_hidden()
    expect(page.locator("#runBtn")).to_be_enabled()
    page.locator("#runBtn").click()
    expect(page.locator("#pipeline-result-title")).to_have_text("Сценарий выполнен", timeout=60000)
    expect(page.locator("#resultValue")).to_contain_text("Retry input")
    assert page.e2e_errors == ["Failed to load resource: the server responded with a status of 503 (Service Unavailable)"]


def test_pipeline_ignores_obsolete_modules_at_unversioned_urls(e2e_server, page):
    obsolete = []

    def legacy_module(route):
        obsolete.append(route.request.url)
        route.fulfill(status=200, content_type="text/javascript", body="throw new Error('Obsolete pipeline module');")

    for name in ("state", "editor", "labels"):
        page.route("**/static/js/pages/pipeline/" + name + ".js", legacy_module)
    page.goto(e2e_server + "/pipeline")
    expect(page.locator("#stepsList .step-card")).to_have_count(3)
    expect(page.locator("#p-0-path")).to_have_value("")
    expect(page.locator(".op-select").first).to_contain_text("Открыть файл")
    page.locator("#operationCatalog > summary").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#opSearch")).to_be_visible()
    assert obsolete == []
    assert page.e2e_errors == []
