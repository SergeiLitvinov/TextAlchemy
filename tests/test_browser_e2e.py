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
    assert page.locator("nav a").count() == 8
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
