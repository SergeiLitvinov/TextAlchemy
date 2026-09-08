"""Реальные browser E2E и автоматическая accessibility-проверка (TODO:128).

Запускается настоящий uvicorn-сервер в отдельном потоке, тесты управляют
headless Chromium через Playwright и прогоняют axe-core для WCAG-проверок.

Требует dev-зависимостей ``playwright`` и ``axe-core-python``, а также
установленного браузера::

    uv run playwright install chromium

Если браузер не установлен, тесты пропускаются, чтобы не ломать обычный
``pytest`` на машинах без playwright.
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

pytest.importorskip("playwright")
pytest.importorskip("axe_core_python")

from playwright.sync_api import Browser, Page, sync_playwright  # noqa: E402

from textalchemy.web.app import app  # noqa: E402
from textalchemy.web.queue import task_queue  # noqa: E402
from textalchemy.web.routes import convert as convert_route  # noqa: E402
from textalchemy.web.tasks import TaskStore  # noqa: E402

PAGES = [
    "/",
    "/extract",
    "/convert",
    "/pipeline",
    "/bibliography",
    "/matching",
    "/reports",
    "/recognize",
    "/generate",
    "/export",
]

_VIEWPORT_WIDTHS = (375, 768, 1280)


def _make_pdf(path: Path, text: str = "E2E Convert Report") -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((50, 72), text, fontsize=14)
    doc.save(str(path))
    doc.close()
    return path


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _ServerThread(threading.Thread):
    def __init__(self, port: int) -> None:
        super().__init__(daemon=True, name="e2e-uvicorn")
        self.port = port
        self.config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(self.config)

    def run(self) -> None:
        self.server.run()


@pytest.fixture(scope="session")
def e2e_server(tmp_path_factory):
    """Реальный HTTP-сервер (uvicorn) поверх того же app, что и TestClient."""
    import importlib

    web_app = importlib.import_module("textalchemy.web.app")

    # Session-фикстура не может использовать function-scoped monkeypatch,
    # поэтому патчим вручную и откатываем в teardown.
    session_patch = pytest.MonkeyPatch()
    session_patch.setattr(web_app, "data_dir", tmp_path_factory.mktemp("e2e-data"))
    session_store = TaskStore(tmp_path_factory.mktemp("e2e-session-tasks"))
    session_patch.setattr(web_app, "tasks_store", session_store)
    session_patch.setattr(convert_route, "tasks_store", session_store)

    port = _free_port()
    thread = _ServerThread(port)
    thread.start()
    try:
        for _ in range(200):
            if thread.server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("uvicorn server did not start")
        yield f"http://127.0.0.1:{port}"
    finally:
        thread.server.should_exit = True
        thread.join(timeout=15)
        session_patch.undo()


@pytest.fixture()
def task_store(tmp_path_factory, monkeypatch):
    """Изолированное хранилище задач на время одного E2E-теста."""
    import importlib

    web_app = importlib.import_module("textalchemy.web.app")
    store = TaskStore(tmp_path_factory.mktemp("e2e-tasks"))
    monkeypatch.setattr(web_app, "tasks_store", store)
    monkeypatch.setattr(convert_route, "tasks_store", store)
    yield store
    task_queue.wait_idle(timeout=30)


@pytest.fixture()
def browser() -> Browser:
    with sync_playwright() as pw:
        try:
            launched = pw.chromium.launch(headless=True)
        except Exception as error:  # noqa: BLE001 - skip gracefully when browsers missing
            pytest.skip(f"playwright browser unavailable: {error}")
        yield launched
        launched.close()


@pytest.fixture()
def page(browser: Browser) -> Page:
    context = browser.new_context()
    current = context.new_page()
    errors: list[str] = []
    current.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    current.on("pageerror", lambda exc: errors.append(str(exc)))
    current.e2e_errors = errors  # type: ignore[attr-defined]
    yield current
    context.close()


def _wait_convert_ready(current: Page) -> None:
    current.wait_for_function(
        "document.getElementById('drop-hint').textContent.includes('PDF')",
        timeout=30000,
    )


def test_e2e_dashboard_loads_without_console_errors(e2e_server, page):
    page.goto(f"{e2e_server}/")
    page.wait_for_load_state("networkidle")
    assert page.locator("h1").first.text_content() == "TextAlchemy"
    assert page.locator("nav a").count() == 10
    assert page.e2e_errors == []


def test_e2e_global_task_center_explains_storage(e2e_server, page):
    page.goto(f"{e2e_server}/")
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name="Задачи").click()

    center = page.get_by_role("complementary", name="Задачи и результаты")
    assert center.get_attribute("inert") is None
    assert "Файлы не отправляются" in center.text_content()
    assert "автоматически очищаются через 1 час" in center.text_content()
    page.keyboard.press("Escape")
    assert page.locator("#taskCenter").get_attribute("inert") is not None


def test_e2e_mobile_navigation_opens_and_closes(e2e_server, page):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{e2e_server}/")
    page.wait_for_load_state("networkidle")

    toggle = page.get_by_role("button", name="Открыть меню")
    toggle.click()
    assert page.locator("body").evaluate("element => element.classList.contains('nav-open')") is True
    assert toggle.get_attribute("aria-expanded") == "true"

    page.keyboard.press("Escape")
    assert page.locator("body").evaluate("element => element.classList.contains('nav-open')") is False
    assert toggle.get_attribute("aria-expanded") == "false"


def test_e2e_generate_document_from_template(e2e_server, page):
    page.goto(f"{e2e_server}/generate")
    page.wait_for_selector("#field-title", timeout=30000)

    page.fill("#field-title", "Проверка шаблона")
    page.fill("#field-author", "TextAlchemy")
    page.fill("#field-body", "Документ создан через пользовательский сценарий.")

    with page.expect_download(timeout=60000) as download_info:
        page.click("#genBtn")
    data = download_info.value.path().read_bytes()
    assert data[:4] == b"PK\x03\x04"
    assert page.locator("#status").text_content() == "Документ сгенерирован и загружен."


def test_e2e_recognize_pdf_text_layer(e2e_server, page, tmp_path):
    pdf = _make_pdf(tmp_path / "recognize.pdf", "Recognized E2E text")
    page.goto(f"{e2e_server}/recognize")

    page.get_by_role("radio", name="Обычный PDF В документе уже можно выделить текст").click()
    page.set_input_files("#fileInput", str(pdf))
    page.wait_for_function("document.getElementById('result').value.includes('Recognized E2E text')", timeout=30000)

    assert page.locator("#scenario").input_value() == "fast"
    assert page.locator("#copyBtn").is_enabled()
    assert "Обработка завершена" in page.locator("#status").text_content()


def test_e2e_extract_text_from_pdf(e2e_server, page, tmp_path):
    pdf = _make_pdf(tmp_path / "extract.pdf", "Extracted E2E content")
    page.goto(f"{e2e_server}/extract")
    page.set_input_files("#fileInput", str(pdf))
    page.wait_for_function("document.getElementById('result').value.includes('Extracted E2E content')", timeout=30000)

    assert page.locator("#copyBtn").is_enabled()
    assert "Извлечено" in page.locator("#status").text_content()


def test_e2e_library_navigation_and_editor(e2e_server, page):
    page.goto(f"{e2e_server}/bibliography")
    tabs = page.get_by_role("navigation", name="Разделы библиотеки")
    assert tabs.get_by_role("link").count() == 4

    page.get_by_role("button", name="Добавить источник").click()
    assert page.locator("#bibEditor").get_attribute("open") is not None
    assert page.locator("#authors").evaluate("element => element === document.activeElement") is True

    tabs.get_by_role("link", name="Связать файлы").click()
    page.wait_for_url(f"{e2e_server}/matching")
    library_tabs = page.get_by_role("navigation", name="Разделы библиотеки")
    assert library_tabs.get_by_role("link", name="Связать файлы").get_attribute("aria-current") == "page"
    assert page.locator("#dryRun").is_checked()


def test_e2e_pipeline_visual_expert_roundtrip(e2e_server, page):
    page.goto(f"{e2e_server}/pipeline")
    page.wait_for_selector("#stepsList .step-card", timeout=30000)

    page.click("#validateBtn")
    page.wait_for_function("document.getElementById('status').textContent.includes('Связи в порядке')")

    page.click("#modeExpertBtn")
    page.wait_for_function("document.getElementById('specText').value.includes('render.latex')")
    assert "title: Demo" in page.locator("#specText").input_value()

    page.click("#toBuilderBtn")
    page.wait_for_function("!document.getElementById('visualMode').hidden")
    assert page.locator("#p-2-title").input_value() == "Demo"
    assert page.e2e_errors == []


def test_e2e_convert_single_pdf_to_docx(e2e_server, page, tmp_path, task_store):
    pdf = _make_pdf(tmp_path / "report.pdf")
    page.goto(f"{e2e_server}/convert")
    _wait_convert_ready(page)

    page.set_input_files("#fileInput", str(pdf))
    page.wait_for_function("document.getElementById('sourceFilename').textContent === 'report.pdf'")
    page.wait_for_function(
        "!['Проверяем…'].includes(document.getElementById('inspectionState').textContent)",
        timeout=30000,
    )

    options = page.locator("#target option").all_text_contents()
    assert any("Word (DOCX)" in option for option in options)
    route_help = page.locator("#route-help").text_content()
    assert "сходство" in route_help and "редактируемость" in route_help

    page.click("#convertBtn")
    page.wait_for_selector("#resultCard:not([hidden])", timeout=120000)
    assert page.locator("#resultTitle").text_content() == "Документ готов"
    assert page.locator("#resultFilename").text_content() == "report.docx"

    with page.expect_download(timeout=60000) as download_info:
        page.click("#downloadBtn")
    downloaded = download_info.value
    data = downloaded.path().read_bytes()
    assert data[:4] == b"PK\x03\x04"  # DOCX = ZIP-архив
    assert page.e2e_errors == []


@pytest.mark.parametrize("budget, rejected", [("", False), ("0", True), ("1", False)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_e2e_quality_budget(e2e_server, page, task_store, monkeypatch, budget, rejected, theme):
    from textalchemy.core.diagnostics import ConversionReport, IssueSeverity

    def export_with_loss(model, output):
        output.write_text("<p>Result</p>", encoding="utf-8")
        report = ConversionReport(output)
        report.add(IssueSeverity.LOSS, "text", "Текст сокращён")
        return report

    monkeypatch.setattr("textalchemy.convert.executor._write_html", export_with_loss)
    page.goto(f"{e2e_server}/convert")
    _wait_convert_ready(page)
    page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
    page.set_viewport_size({"width": 375, "height": 900})
    page.set_input_files("#fileInput", {"name": "source.txt", "mimeType": "text/plain", "buffer": b"Original"})
    page.select_option("#target", "html")
    page.locator(".conversion-loss-budget summary").click()
    page.select_option("#maxLossIssues", budget)
    with page.expect_response(
        lambda response: response.url.endswith('/api/convert') and response.request.method == 'POST'
    ) as response:
        page.click("#convertBtn")
    created = response.value.json()
    page.wait_for_selector("#resultCard:not([hidden])", timeout=30000)
    stored = task_store.get(created["task_id"])
    assert stored["max_loss_issues"] == (int(budget) if budget else None)
    assert page.locator("#downloadBtn").is_visible() is not rejected
    summary = page.locator("#qualityGateSummary").inner_text()
    if rejected:
        assert "Результат не выдан" in summary
        assert page.locator("#qualityBadge").inner_text() == "Превышен бюджет потерь"
        assert not stored.get("artifact")
    elif budget:
        assert "Бюджет соблюдён" in summary
    else:
        assert "не проверялся" in summary
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.e2e_errors == []


def test_e2e_download_editable_pptx(e2e_server, page, tmp_path, task_store):
    from pptx import Presentation

    page.goto(f"{e2e_server}/convert")
    _wait_convert_ready(page)
    page.set_input_files("#fileInput", {
        "name": "slide.txt", "mimeType": "text/plain", "buffer": "Редактируемый слайд".encode(),
    })
    page.select_option("#target", "pptx")
    page.click("#convertBtn")
    page.wait_for_selector("#resultCard:not([hidden])", timeout=30000)
    assert page.locator("#downloadBtn").is_visible()
    with page.expect_download() as pending:
        page.click("#downloadBtn")
    path = tmp_path / pending.value.suggested_filename
    pending.value.save_as(path)
    assert path.suffix == ".pptx"
    assert Presentation(path).slides[0].shapes[0].text == "Редактируемый слайд"
    assert page.e2e_errors == []


def test_e2e_batch_passes_quality_budget_to_each_file(e2e_server, page, task_store):
    page.goto(f"{e2e_server}/convert")
    _wait_convert_ready(page)
    page.set_input_files("#fileInput", [
        {"name": "first.txt", "mimeType": "text/plain", "buffer": b"First"},
        {"name": "second.txt", "mimeType": "text/plain", "buffer": b"Second"},
    ])
    page.select_option("#target", "model")
    page.locator(".conversion-loss-budget summary").click()
    page.select_option("#maxLossIssues", "0")
    page.select_option("#maxLostObjects", "0")
    page.select_option("#textPreservation", "paragraphs")
    with page.expect_response(lambda response: response.url.endswith('/api/convert/batch')) as response:
        page.click("#batchConvertBtn")
    created = response.value.json()
    page.wait_for_function("document.getElementById('batchProgressState').textContent === 'Готово'", timeout=30000)
    for item in created["tasks"]:
        task = task_store.get(item["task_id"])
        assert task["status"] == "done"
        assert task["max_loss_issues"] == 0
        assert task["max_lost_objects"] == 0
        assert task["report"]["metrics"]["object_quality_gate"]["accepted"] is True
        assert task["text_preservation"] == "paragraphs"
        assert task["report"]["metrics"]["text_quality_gate"]["accepted"] is True
        assert task["report"]["metrics"]["quality_gate"]["accepted"] is True
    assert page.e2e_errors == []


@pytest.mark.parametrize("target, accepted", [("docx", True), ("html", False)])
def test_e2e_object_budget_reports_verification(e2e_server, page, task_store, target, accepted):
    page.goto(f"{e2e_server}/convert")
    _wait_convert_ready(page)
    page.set_input_files("#fileInput", {"name": "source.txt", "mimeType": "text/plain", "buffer": b"Unique text"})
    page.select_option("#target", target)
    page.locator(".conversion-loss-budget summary").click()
    page.select_option("#maxLostObjects", "0")
    page.click("#convertBtn")
    page.wait_for_selector("#resultCard:not([hidden])", timeout=30000)
    summary = page.locator("#objectGateSummary").inner_text()
    assert ("Бюджет объектов соблюдён" if accepted else "не удалось проверить") in summary
    assert page.locator("#downloadBtn").is_visible() is accepted
    assert page.e2e_errors == []


@pytest.mark.parametrize("changed", [False, True])
def test_e2e_exact_text_check(e2e_server, page, task_store, monkeypatch, changed):
    from textalchemy.convert.docx_writer import write_docx_model
    from textalchemy.core.document_model import TextRun

    def export(model, output):
        if changed:
            model.sections[0].blocks[0].content = [TextRun("Replaced")]
        return write_docx_model(model, output)

    monkeypatch.setattr("textalchemy.convert.executor._write_docx", export)
    page.goto(f"{e2e_server}/convert")
    _wait_convert_ready(page)
    page.set_viewport_size({"width": 375, "height": 900})
    page.set_input_files("#fileInput", {"name": "source.txt", "mimeType": "text/plain", "buffer": b"Original"})
    page.select_option("#target", "docx")
    page.locator(".conversion-loss-budget summary").click()
    page.select_option("#textPreservation", "paragraphs")
    page.click("#convertBtn")
    page.wait_for_selector("#resultCard:not([hidden])", timeout=30000)
    summary = page.locator("#textGateSummary").inner_text()
    assert ("Не совпал текст" if changed else "сохранён дословно") in summary
    assert page.locator("#downloadBtn").is_visible() is not changed
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.e2e_errors == []


@pytest.mark.parametrize("mode, accepted", [("paragraphs", False), ("flow", True)])
def test_e2e_text_reflow_mode(e2e_server, page, task_store, monkeypatch, mode, accepted):
    from textalchemy.convert.docx_writer import write_docx_model
    from textalchemy.core.document_model import Paragraph, TextRun

    def export(model, output):
        model.sections[0].blocks = [Paragraph(content=[TextRun(word)]) for word in ["First", "Second"]]
        return write_docx_model(model, output)

    monkeypatch.setattr("textalchemy.convert.executor._write_docx", export)
    page.goto(f"{e2e_server}/convert")
    _wait_convert_ready(page)
    page.set_viewport_size({"width": 375, "height": 900})
    page.set_input_files("#fileInput", {"name": "source.txt", "mimeType": "text/plain", "buffer": b"First Second"})
    page.select_option("#target", "docx")
    page.locator(".conversion-loss-budget summary").click()
    page.select_option("#textPreservation", mode)
    page.click("#convertBtn")
    page.wait_for_selector("#resultCard:not([hidden])", timeout=30000)
    summary = page.locator("#textGateSummary").inner_text()
    assert ("Последовательность текста сохранена" if accepted else "Не совпал текст") in summary
    assert page.locator("#downloadBtn").is_visible() is accepted
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.e2e_errors == []


def test_e2e_convert_batch_flow(e2e_server, page, tmp_path, task_store):
    page.goto(f"{e2e_server}/convert")
    _wait_convert_ready(page)

    pdfs = [_make_pdf(tmp_path / "a.pdf", "Batch A"), _make_pdf(tmp_path / "b.pdf", "Batch B")]
    page.set_input_files("#fileInput", [str(path) for path in pdfs])
    page.wait_for_function(
        "document.getElementById('batchFileBlock') && !document.getElementById('batchFileBlock').hidden"
    )
    assert "2 файлов" in page.locator("#batchFileSummary").text_content()

    page.click("#batchConvertBtn")
    page.wait_for_selector("#batchProgressCard:not([hidden])", timeout=60000)
    page.wait_for_function(
        "document.getElementById('batchProgressState').textContent === 'Готово'",
        timeout=120000,
    )
    done_items = page.locator("#batchProgressList .batch-progress-item.done")
    assert done_items.count() == 2

    page.wait_for_selector("#historyList details.job-entry", timeout=30000)
    page.locator("#historyList details.job-entry summary").first.click()
    page.wait_for_selector("[data-rerun-job]", timeout=30000)
    page.click("[data-rerun-job]")
    page.locator("#toast-container div").first.wait_for(timeout=30000)
    assert "перезапущена" in page.locator("#toast-container").inner_text().lower()
    page.wait_for_function(
        "document.getElementById('batchProgressState').textContent === 'Готово'",
        timeout=120000,
    )

    page.wait_for_selector("#historyList details.job-entry", timeout=30000)
    page.locator("#historyList details.job-entry summary").first.click()
    page.wait_for_selector("[data-delete-job]", timeout=30000)
    page.click("[data-delete-job]")
    page.wait_for_function(
        "document.querySelectorAll('#historyList details.job-entry').length === 0",
        timeout=30000,
    )
    assert page.e2e_errors == []


def test_e2e_dropzone_is_keyboard_operable(e2e_server, page, tmp_path):
    pdf = _make_pdf(tmp_path / "keyboard.pdf")
    page.goto(f"{e2e_server}/convert")
    _wait_convert_ready(page)

    dropzone = page.locator("#dropZone")
    dropzone.focus()
    assert page.evaluate("document.activeElement.id") == "dropZone"
    with page.expect_file_chooser() as chooser_info:
        page.keyboard.press("Enter")
    chooser_info.value.set_files(str(pdf))
    page.wait_for_function("document.getElementById('sourceFilename').textContent === 'keyboard.pdf'")


def test_e2e_dropzone_reachable_via_tab(e2e_server, page):
    page.goto(f"{e2e_server}/convert")
    _wait_convert_ready(page)
    for _ in range(20):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.id") == "dropZone":
            break
    assert page.evaluate("document.activeElement.id") == "dropZone"


@pytest.mark.parametrize("width", _VIEWPORT_WIDTHS)
def test_e2e_pages_have_no_horizontal_overflow(e2e_server, page, width):
    page.set_viewport_size({"width": width, "height": 800})
    for path in PAGES:
        page.goto(f"{e2e_server}{path}")
        page.wait_for_load_state("networkidle")
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, f"{path} @{width}px: horizontal overflow {overflow}px"


def test_e2e_axe_accessibility_no_serious_violations(e2e_server, page):
    from axe_core_python.sync_playwright import Axe

    axe = Axe()
    for path in ("/", "/convert", "/extract", "/pipeline"):
        page.goto(f"{e2e_server}{path}")
        page.wait_for_load_state("networkidle")
        results = axe.run(page)
        serious = [
            v for v in results["violations"] if v.get("impact") in ("serious", "critical")
        ]
        assert not serious, (
            f"{path}: axe serious/critical: "
            + repr([(v["id"], v["impact"], v["help"]) for v in serious])
        )


def test_e2e_convert_controls_have_accessible_names(e2e_server, page, tmp_path, task_store):
    pdf = _make_pdf(tmp_path / "names.pdf")
    page.goto(f"{e2e_server}/convert")
    _wait_convert_ready(page)

    assert page.get_by_role("heading", name="Сохранить документ, а не просто текст").count() == 1
    dropzone = page.get_by_role("button", name="Загрузите документ")
    assert dropzone.count() == 1

    # Контролы конвертации появляются только после выбора файла.
    page.set_input_files("#fileInput", str(pdf))
    page.wait_for_function(
        "!document.getElementById('conversionSetup').hidden"
    )
    assert page.get_by_role("combobox", name="Формат результата").count() == 1
    assert page.get_by_role("combobox", name="Приоритет").count() == 1
    assert page.get_by_role("button", name="Начать конвертацию").count() == 1
    assert page.get_by_role("button", name="Выбрать другой").count() == 1
