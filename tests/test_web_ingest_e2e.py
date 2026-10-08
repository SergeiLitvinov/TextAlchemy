"""Явный запуск, повтор после ошибки и сохранность ввода на новых экранах."""

from pathlib import Path
from typing import Any

import pytest
from axe_core_python.sync_playwright import Axe
from playwright.sync_api import Page, expect

from tests import test_browser_e2e as fixtures
from textalchemy.web.routes import extract as extract_route
from textalchemy.web.services.recognition import RecognitionService

browser, page, e2e_server, task_store = fixtures.browser, fixtures.page, fixtures.e2e_server, fixtures.task_store


@pytest.mark.parametrize("width", [375, 768, 1280])
@pytest.mark.parametrize("kind", ["extract", "recognize"])
def test_file_options_explicit_keyboard_start_and_result(
    e2e_server: str, page: Page, task_store: Any, tmp_path: Path, width: int, kind: str
) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/" + kind)
    posts = []
    page.on("request", lambda request: posts.append(request) if request.method == "POST" else None)
    expect(page.locator("#resultEmpty")).to_be_visible()
    expect(page.locator("#processBtn")).to_be_disabled()
    source = fixtures._make_pdf(tmp_path / "Документ.pdf", "User can check options first")
    page.locator("#fileInput").set_input_files(source)
    expect(page.locator("#selectedFile")).to_contain_text("Документ.pdf")
    if kind == "recognize":
        page.locator("#scenario").select_option("fast")
        page.locator("#lang").select_option("eng")
    expect(page.locator("#resultEmpty")).to_be_visible()
    assert posts == []
    assert not [item for item in Axe().run(page)["violations"] if item.get("impact") in ("serious", "critical")]
    page.locator("#processBtn").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#result")).to_have_value("User can check options first", timeout=30000)
    expect(page.locator("#resultCard")).to_be_visible()
    expect(page.locator("#resultSource")).to_have_text("Документ.pdf")
    expect(page.locator("#processBtn")).to_be_enabled()
    assert len(posts) == 1
    if kind == "extract":
        with page.expect_download() as pending:
            page.locator("#downloadBtn").click()
        assert pending.value.suggested_filename == "Документ.txt"
        assert pending.value.path().read_text(encoding="utf-8") == "User can check options first"
        page.locator("#output-kind").select_option("latex")
        expect(page.locator("#extract-result-title")).to_have_text("Извлечённый текст")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not [item for item in Axe().run(page)["violations"] if item.get("impact") in ("serious", "critical")]
    page.screenshot(path=str(tmp_path / f"{kind}-{width}.png"))
    assert page.e2e_errors == []


def test_image_uses_ocr_and_keeps_expert_settings_after_failure(
    e2e_server: str, page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import Image

    calls = []

    def read(_self: Any, source: Path, **options: Any) -> dict:
        calls.append((source.name, options))
        return {"success": False, "error": "Для изображения требуется OCR"}

    monkeypatch.setattr(RecognitionService, "_read", read)
    source = tmp_path / "photo.png"
    Image.new("RGB", (8, 8), "white").save(source)
    page.goto(e2e_server + "/recognize")
    page.locator("#scenario").select_option("fast")
    page.locator("#fileInput").set_input_files(source)
    expect(page.locator("#scenarioOptions")).to_be_hidden()
    expect(page.locator("#scenarioHint")).to_contain_text("изображения используется OCR")
    page.locator("#lang").select_option("rus")
    page.get_by_text("Рукописный текст и ускорение", exact=True).click()
    page.locator("#mode").select_option("handwriting")
    page.locator("#gpu").check()
    assert calls == []
    page.locator("#processBtn").click()
    expect(page.locator("#status")).to_contain_text("Для изображения требуется OCR")
    assert calls == [("photo.png", {"lang": "rus", "gpu": True, "mode": "handwriting", "scenario": "scan"})]
    expect(page.locator("#mode")).to_have_value("handwriting")
    expect(page.locator("#gpu")).to_be_checked()
    expect(page.locator("#processBtn")).to_be_enabled()
    assert page.e2e_errors == []


@pytest.mark.parametrize("kind", ["extract", "recognize"])
def test_failed_request_keeps_file_settings_and_previous_result_for_retry(
    e2e_server: str, page: Page, task_store: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    page.goto(e2e_server + "/" + kind)
    page.locator("#fileInput").set_input_files(fixtures._make_pdf(tmp_path / "source.pdf", "Previous result"))
    if kind == "recognize":
        page.locator("#scenario").select_option("fast")
        page.locator("#lang").select_option("eng")
    page.locator("#processBtn").click()
    expect(page.locator("#result")).to_have_value("Previous result", timeout=30000)

    if kind == "extract":
        original = extract_route.extract_text

        def fail(**_kwargs: Any) -> None:
            raise ValueError("Cannot read source")

        monkeypatch.setattr(extract_route, "extract_text", fail)
    else:
        original = RecognitionService._read
        monkeypatch.setattr(RecognitionService, "_read", lambda *_args, **_kwargs: {"success": False, "error": "OCR unavailable"})
    page.locator("#processBtn").click()
    expect(page.locator("#status")).to_contain_text("Cannot read source" if kind == "extract" else "OCR unavailable")
    expect(page.locator("#result")).to_have_value("Previous result")
    expect(page.locator("#selectedFile")).to_contain_text("source.pdf")
    expect(page.locator("#processBtn")).to_be_enabled()
    if kind == "recognize":
        expect(page.locator("#lang")).to_have_value("eng")
        expect(page.locator("#scenario")).to_have_value("fast")
        monkeypatch.setattr(RecognitionService, "_read", original)
    else:
        monkeypatch.setattr(extract_route, "extract_text", original)
    page.locator("#processBtn").click()
    expect(page.locator("#status")).to_have_class("status-bar success")
    expect(page.locator("#result")).to_have_value("Previous result")
    assert page.e2e_errors == []


def test_latex_failure_is_not_shown_as_result_and_retry_uses_same_docx(
    e2e_server: str, page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from docx import Document

    source = tmp_path / "Исходник.docx"
    Document().save(source)
    page.goto(e2e_server + "/extract")
    page.locator("#fileInput").set_input_files(source)
    page.locator("#output-kind").select_option("latex")

    def fail(*_args: Any) -> None:
        raise ValueError("Failed to prepare LaTeX")

    monkeypatch.setattr(extract_route, "docx_to_latex", fail)
    page.locator("#processBtn").click()
    expect(page.locator("#status")).to_contain_text("Failed to prepare LaTeX")
    expect(page.locator("#resultEmpty")).to_be_visible()
    expect(page.locator("#output-kind")).to_have_value("latex")

    def recovered(path: Path, target: Path, _kind: str) -> None:
        assert path.name == source.name
        target.write_text(r"\section{Result}", encoding="utf-8")

    monkeypatch.setattr(extract_route, "docx_to_latex", recovered)
    page.locator("#processBtn").click()
    expect(page.locator("#result")).to_have_value(r"\section{Result}")
    expect(page.locator("#extract-result-title")).to_have_text("Исходник LaTeX")
    with page.expect_download() as pending:
        page.locator("#downloadBtn").click()
    assert pending.value.suggested_filename == "Исходник.tex"
    assert pending.value.path().read_text(encoding="utf-8") == r"\section{Result}"
    assert page.e2e_errors == []
