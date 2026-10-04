"""Simple conversion, explicit expert constraints and return to defaults."""

import pytest

from tests import test_browser_e2e as fixtures

browser, page, e2e_server, task_store = fixtures.browser, fixtures.page, fixtures.e2e_server, fixtures.task_store


@pytest.mark.parametrize("width", [375, 768, 1280])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_conversion_modes_reset_hidden_constraints_and_keep_warnings(e2e_server, page, task_store, width, theme):
    from axe_core_python.sync_playwright import Axe
    from playwright.sync_api import expect

    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/convert")
    fixtures._wait_convert_ready(page)
    page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
    expect(page.locator("#simpleConversionBtn")).to_have_attribute("aria-pressed", "true")
    page.locator("#fileInput").set_input_files({"name": "note.txt", "mimeType": "text/plain", "buffer": b"Original text"})
    expect(page.locator("#mode")).to_be_hidden()
    expect(page.locator(".conversion-loss-budget")).to_be_hidden()
    page.locator("#expertConversionBtn").click()
    expect(page.locator("#mode")).to_be_visible()
    page.locator(".conversion-loss-budget summary").click()
    page.locator("#mode").select_option("editable")
    page.locator("#maxChangedFormulas").fill("0")
    page.locator("#maxChangedEmphasis").fill("0")
    page.locator("#maxLossIssues").select_option("0")
    page.locator("#textPreservation").select_option("flow")
    page.locator("#maxTextEdits").fill("2")
    page.locator("#simpleConversionBtn").click()
    expect(page.locator("#mode")).to_be_hidden()
    assert page.locator("#mode").input_value() == "balanced"
    assert page.locator("#maxTextEdits").is_disabled()
    for control in ["maxChangedFormulas", "maxChangedEmphasis", "maxLossIssues", "textPreservation"]:
        assert page.locator("#" + control).input_value() == ""
    page.locator("#target").select_option("pptx")
    expect(page.locator("#routeGuidance")).to_be_visible()
    with page.expect_response(
        lambda response: response.url.endswith("/api/convert") and response.request.method == "POST"
    ) as pending:
        page.locator("#convertBtn").click()
    task_id = pending.value.json()["task_id"]
    expect(page.locator("#resultCard")).to_be_visible(timeout=60000)
    expect(page.locator('.conversion-workflow [aria-current="step"]')).to_contain_text("Проверка")
    expect(page.locator("#downloadBtn")).to_be_visible()
    task = task_store.get(task_id)
    assert task["mode"] == "balanced"
    assert task.get("max_changed_formulas") is None
    assert task.get("max_changed_emphasis") is None
    assert task.get("max_loss_issues") is None
    assert page.locator("#resultCard").evaluate(
        '(el) => !!(el.compareDocumentPosition(document.querySelector(".conversion-history")) & Node.DOCUMENT_POSITION_FOLLOWING)'
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not [item for item in Axe().run(page)["violations"] if item.get("impact") in ("serious", "critical")]
    page.reload()
    expect(page.locator("#simpleConversionBtn")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#conversionSetup")).to_be_hidden()
    assert page.e2e_errors == []


@pytest.mark.parametrize("width", [375, 768, 1280])
def test_expert_single_conversion_saves_and_applies_strict_constraints(e2e_server, page, task_store, width):
    from playwright.sync_api import expect

    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/convert")
    fixtures._wait_convert_ready(page)
    page.locator("#fileInput").set_input_files({"name": "strict.txt", "mimeType": "text/plain", "buffer": b"Keep this text"})
    page.locator("#expertConversionBtn").click()
    page.locator("#target").select_option("model")
    page.locator("#mode").select_option("editable")
    page.locator(".conversion-loss-budget summary").click()
    page.locator("#textPreservation").select_option("paragraphs")
    page.locator("#maxChangedFormulas").fill("0")
    page.locator("#maxChangedEmphasis").fill("0")
    with page.expect_response(
        lambda response: "/api/convert/preview/" in response.url and response.url.endswith("/meta"), timeout=210000
    ) as meta:
        with page.expect_response(
            lambda response: response.url.endswith("/api/convert") and response.request.method == "POST"
        ) as pending:
            page.locator("#convertBtn").click()
        task_id = pending.value.json()["task_id"]
        expect(page.locator("#resultTitle")).to_have_text("Документ готов", timeout=60000)
    if any(side["available"] for side in meta.value.json().values()):
        page.wait_for_function("document.querySelector('#previewCanvas img')?.naturalWidth > 0")
    expect(page.locator("#downloadBtn")).to_be_visible()
    task = task_store.get(task_id)
    assert task["status"] == "done" and task["mode"] == "editable"
    assert task["text_preservation"] == "paragraphs"
    assert task["max_changed_formulas"] == 0 and task["max_changed_emphasis"] == 0
    assert "Keep this text" in task_store.result_path(task_id, task["artifact"]).read_text(encoding="utf-8")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.e2e_errors == []


@pytest.mark.parametrize("width", [375, 768, 1280])
@pytest.mark.parametrize("expert", [False, True])
def test_conversion_submit_failure_preserves_input_and_locks_form(e2e_server, page, width, expert):
    from playwright.sync_api import expect

    held = []
    page.route("**/api/convert", lambda route: held.append(route))
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/convert")
    fixtures._wait_convert_ready(page)
    expect(page.locator("#conversionSetup")).to_be_hidden()
    assert not page.locator("#conversionHistory").evaluate("el => el.open")
    with page.expect_file_chooser() as chooser:
        # Keep the key press attached to the intended control in slow browser runs.
        page.locator("#dropZone").press("Enter")
    chooser.value.set_files({"name": "retained.txt", "mimeType": "text/plain", "buffer": b"Retained input"})
    expect(page.locator("#filePickerWrap")).to_be_hidden()
    page.locator("#target").select_option("model")
    if expert:
        page.locator("#expertConversionBtn").click()
        page.locator("#mode").select_option("editable")
        page.locator(".conversion-loss-budget summary").click()
        page.locator("#maxChangedFormulas").fill("0")
    with page.expect_request("**/api/convert"):
        page.locator("#convertBtn").click()
    expect(page.locator("#target")).to_be_disabled()
    expect(page.locator("#replaceBtn")).to_be_disabled()
    expect(page.locator("#simpleConversionBtn")).to_be_disabled()
    assert len(held) == 1
    held[0].fulfill(status=503, json={"detail": "Очередь временно недоступна"})
    expect(page.locator("#status")).to_contain_text("Очередь временно недоступна")
    expect(page.locator("#sourceFilename")).to_have_text("retained.txt")
    expect(page.locator("#target")).to_be_enabled()
    expect(page.locator("#replaceBtn")).to_be_enabled()
    assert page.locator("#target").input_value() == "model"
    assert page.locator("#mode").input_value() == ("editable" if expert else "balanced")
    if expert:
        assert page.locator("#maxChangedFormulas").input_value() == "0"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.e2e_errors == [
        "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
    ]


@pytest.mark.parametrize("width", [375, 768, 1280])
def test_history_download_matches_displayed_result_and_priority(e2e_server, page, task_store, tmp_path, width):
    from playwright.sync_api import expect

    from tests.test_web_preview_e2e import seed

    seed(task_store, tmp_path, "first", pages=1)
    seed(task_store, tmp_path, "second", pages=2)
    metadata = task_store.get("second")
    task_store.set("second", {**metadata, "mode": "editable"})
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/convert")
    fixtures._wait_convert_ready(page)
    page.locator("#conversionHistory > summary").focus()
    page.keyboard.press("Enter")
    for summary in page.locator("#historyList details summary").all():
        summary.click()
    for task_id, priority in [("first", "Разумный баланс"), ("second", "Можно удобно редактировать")]:
        page.locator(f'[data-preview-task="{task_id}"]').click()
        expect(page.locator("#resultFilename")).to_have_text(f"{task_id}-target.pdf")
        expect(page.locator("#resultMode")).to_have_text(priority)
        expect(page.locator("#qualityBadge")).to_have_text("Отчёт о качестве недоступен")
        page.wait_for_function("document.querySelector('#previewCanvas img')?.naturalWidth > 0")
        with page.expect_download() as download:
            page.locator("#downloadBtn").click()
        saved = tmp_path / download.value.suggested_filename
        download.value.save_as(saved)
        task = task_store.get(task_id)
        assert saved.read_bytes() == task_store.result_path(task_id, task["artifact"]).read_bytes()
    assert page.locator("#downloadBtn").evaluate(
        'el => !!(el.compareDocumentPosition(document.querySelector(".result-summary")) & Node.DOCUMENT_POSITION_FOLLOWING)'
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.e2e_errors == []


@pytest.mark.parametrize("width", [375, 768, 1280])
@pytest.mark.parametrize("expert", [False, True])
def test_conversion_batch_modes_download_real_archive(e2e_server, page, task_store, tmp_path, width, expert):
    import json
    from zipfile import ZipFile

    from playwright.sync_api import expect

    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/convert")
    fixtures._wait_convert_ready(page)
    page.locator("#fileInput").set_input_files(
        [
            {"name": "first.txt", "mimeType": "text/plain", "buffer": b"First document"},
            {"name": "second.txt", "mimeType": "text/plain", "buffer": b"Second document"},
        ]
    )
    page.locator("#target").select_option("model")
    if expert:
        page.locator("#expertConversionBtn").click()
        page.locator("#mode").select_option("editable")
        page.locator(".conversion-loss-budget summary").click()
        page.locator("#maxChangedFormulas").fill("0")
    with page.expect_response("**/api/convert/batch") as submitted:
        page.locator("#batchConvertBtn").click()
    expect(page.locator("#batchProgressState")).to_have_text("Готово", timeout=60000)
    expect(page.locator("#batchProgressList .batch-progress-item.done")).to_have_count(2)
    assert not page.locator("#batchFilters").evaluate("el => el.open")
    for item in submitted.value.json()["tasks"]:
        task = task_store.get(item["task_id"])
        assert task["mode"] == ("editable" if expert else "balanced")
        assert task.get("max_changed_formulas") == (0 if expert else None)
    with page.expect_download() as download:
        page.locator("#batchArchiveBtn").click()
    saved = tmp_path / "results.zip"
    download.value.save_as(saved)
    with ZipFile(saved) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert len(manifest["files"]) == 2
        assert all(item["status"] == "done" and item["file"] in archive.namelist() for item in manifest["files"])
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.e2e_errors == []
