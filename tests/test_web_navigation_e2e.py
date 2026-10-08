"""Проверки окон, фокуса и последовательности работы с редактором."""

import pytest
from playwright.sync_api import Page, Route, expect

from tests import test_browser_e2e as fixtures

browser, e2e_server, page = fixtures.browser, fixtures.e2e_server, fixtures.page


@pytest.mark.parametrize("width", [375, 1280])
def test_tasks_keep_focus_and_confirm_cleanup(e2e_server: str, page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 844})
    deleted = []
    page.route(
        "**/api/tasks",
        lambda route: route.fulfill(
            json={
                "active": 0,
                "storage": {"bytes": 0},
                "tasks": [{"filename": "example.docx", "status": "done", "task_id": "example"}],
            }
        ),
    )
    page.route("**/api/tasks/finished", lambda route: (deleted.append(route.request.method), route.fulfill(json={})))
    page.goto(f"{e2e_server}/")
    trigger = page.get_by_role("button", name="Открыть задачи", exact=True)
    trigger.click()
    center = page.get_by_role("dialog", name="Задачи и результаты", exact=True)
    close = center.get_by_role("button", name="Закрыть центр задач")
    expect(close).to_be_focused()
    close.press("Shift+Tab")
    expect(center.get_by_role("link", name="Новая конвертация")).to_be_focused()
    center.get_by_role("link", name="Новая конвертация").press("Tab")
    expect(close).to_be_focused()
    assert page.locator(".app-layout").evaluate("el => el.inert")
    center.get_by_role("button", name="Очистить завершённые").click()
    dialog = page.get_by_role("dialog", name="Удалить завершённые задачи?")
    dialog.get_by_role("button", name="Оставить задачи").click()
    assert deleted == []
    center.get_by_role("button", name="Очистить завершённые").click()
    dialog.get_by_role("button", name="Удалить завершённые", exact=True).click()
    expect(page.locator("#toast-container")).to_contain_text("Завершённые задачи удалены")
    assert deleted == ["DELETE"]
    center.get_by_role("button", name="Очистить завершённые").click()
    dialog.press("Escape")
    expect(center).to_be_visible()
    assert deleted == ["DELETE"]
    close.press("Escape")
    expect(trigger).to_be_focused()
    assert not page.locator(".app-layout").evaluate("el => el.inert")
    assert page.e2e_errors == []


def test_mobile_menu_and_tasks_are_exclusive(e2e_server: str, page: Page) -> None:
    page.set_viewport_size({"width": 375, "height": 844})
    page.goto(f"{e2e_server}/extract")
    page.wait_for_load_state("networkidle")
    sidebar = page.locator("#app-sidebar")
    assert sidebar.evaluate("el => el.inert")
    toggle = page.get_by_role("button", name="Открыть меню", exact=True)
    toggle.click()
    expect(sidebar.locator('a[aria-current="page"]')).to_be_focused()
    assert page.locator("main").evaluate("el => el.inert")
    sidebar.get_by_role("button", name="Файлы и задачи", exact=False).click()
    expect(page.get_by_role("dialog", name="Задачи и результаты")).to_be_visible()
    assert not page.locator("body").evaluate("el => el.classList.contains('nav-open')")
    assert sidebar.evaluate("el => el.inert")
    page.get_by_role("button", name="Закрыть центр задач").press("Escape")
    expect(page.get_by_role("button", name="Открыть задачи", exact=True)).to_be_focused()
    toggle.click()
    page.get_by_role("button", name="Закрыть меню", exact=True).press("Escape")
    expect(toggle).to_be_focused()
    page.set_viewport_size({"width": 1280, "height": 844})
    expect(sidebar).not_to_have_attribute("inert", "")
    assert page.e2e_errors == []


def test_task_refresh_preserves_keyboard_focus(e2e_server: str, page: Page) -> None:
    responses = []

    def task_response(route: Route) -> None:
        responses.append(True)
        route.fulfill(
            json={
                "active": 1,
                "storage": {"bytes": 0},
                "tasks": [
                    {"filename": "ready.docx", "status": "done", "task_id": "ready", "result_url": "/result.docx"},
                    {"filename": "working.txt", "status": "running", "task_id": "working"},
                ],
            }
        )

    page.route("**/api/tasks", task_response)
    page.goto(f"{e2e_server}/")
    page.get_by_role("button", name="Открыть задачи", exact=True).click()
    download = page.locator('#taskCenter a[data-task-focus="download"]')
    expect(download).to_be_visible()
    download.focus()
    with page.expect_response("**/api/tasks"):
        expect(download).to_be_focused()
    expect(download).to_be_focused()
    assert len(responses) >= 2
    assert page.e2e_errors == []


def test_template_editor_shows_source_without_generating(e2e_server: str, page: Page) -> None:
    page.goto(f"{e2e_server}/generate")
    fixtures._generator_step(page)
    expect(page.locator("#field-title")).to_be_visible(timeout=30000)
    page.locator("#field-title").fill("Проверка режимов")
    page.locator("#editMode").click()
    expect(page.locator("#preview-title")).to_have_text("Исходный шаблон")
    expect(page.locator("#filledPreview")).to_be_hidden()
    expect(page.locator("#previewSource")).to_be_hidden()
    page.locator("#sourceEditor > summary").click()
    expect(page.locator("#sourceQuery")).to_be_hidden()
    page.locator("#sourceInspect").click()
    expect(page.locator("#sourceQuery")).to_be_visible(timeout=30000)
    expect(page.locator("#sourceBlocks")).to_be_focused()
    page.locator("#fillMode").click()
    expect(page.locator("#field-title")).to_have_value("Проверка режимов")
    expect(page.locator("#livePreview")).to_be_visible()
    assert page.e2e_errors == []


def test_pipeline_modes_work_with_arrow_keys(e2e_server: str, page: Page) -> None:
    page.goto(f"{e2e_server}/pipeline")
    expect(page.locator(".step-card")).to_have_count(3)
    visual = page.get_by_role("tab", name="Конструктор")
    expert = page.get_by_role("tab", name="Текстовый режим")
    visual.press("ArrowRight")
    expect(expert).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tabpanel", name="Текстовый режим")).to_be_visible()
    expert.press("ArrowLeft")
    expect(visual).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tabpanel", name="Конструктор")).to_be_visible()
    assert page.e2e_errors == []


@pytest.mark.parametrize(
    "route,chapter,title",
    [
        ("generate", "templates", "Документы из шаблонов"),
        ("recognize", "recognition", "Распознавание и извлечение"),
        ("extract", "recognition", "Распознавание и извлечение"),
        ("matching", "bibliography", "Библиотека и библиография"),
    ],
)
def test_context_help_keeps_document_form_open(e2e_server: str, page: Page, route: str, chapter: str, title: str) -> None:
    """Справка открывает нужную главу и сохраняет рабочую форму пользователя."""
    page.goto(f"{e2e_server}/{route}")
    if route == "generate":
        fixtures._generator_step(page)
        page.locator("#field-title").fill("Документ остаётся открытым")
    with page.expect_popup() as popup_info:
        page.locator(f'.page-heading a[href="/help/doc/guide/{chapter}/"]').click()
    popup = popup_info.value
    expect(popup.locator("main h1").first).to_have_text(title)
    assert page.url == f"{e2e_server}/{route}"
    if route == "generate":
        expect(page.locator("#field-title")).to_have_value("Документ остаётся открытым")
    popup.close()
    assert page.e2e_errors == []


@pytest.mark.parametrize("width", [375, 1280])
def test_pipeline_step_controls_have_consistent_targets(e2e_server: str, page: Page, width: int) -> None:
    """Перемещение и удаление имеют одинаковые доступные области на обоих экранах."""
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{e2e_server}/pipeline")
    expect(page.locator(".step-card")).to_have_count(3)
    controls = page.locator(".step-card").nth(1).locator(".step-actions button")
    assert controls.count() == 3
    for control in controls.all():
        bounds = control.bounding_box()
        assert bounds["width"] == bounds["height"] == 44
    # Перемещение действительно меняет порядок; удаление действует на выбранный шаг.
    before = [control.input_value() for control in page.locator(".step-card .op-select").all()]
    page.locator(".step-card").nth(1).get_by_role("button", name="Выше", exact=True).click()
    assert page.locator(".step-card .op-select").first.input_value() == before[1]
    page.locator(".step-card").first.get_by_role("button", name="Удалить", exact=True).click()
    expect(page.locator(".step-card")).to_have_count(2)
    assert page.locator(".step-card .op-select").first.input_value() == before[0]
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.e2e_errors == []


def test_download_validation_returns_to_fields_and_survives_preview(e2e_server: str, page: Page) -> None:
    """Обновление черновика не скрывает причину отказа в скачивании документа."""
    updates: list[str] = []

    def live_response(route: Route) -> None:
        updates.append(f"Просмотр {len(updates) + 1}")
        route.fulfill(
            json={
                "success": True,
                "html": f"<html><head></head><body>{updates[-1]}</body></html>",
                "draft": False,
                "missing_fields": [],
            }
        )

    page.route("**/api/generate/live-preview", live_response)
    page.route(
        "**/api/generate",
        lambda route: route.fulfill(
            json={
                "success": False,
                "error": "Проверьте заголовок",
                "errors": {"title": "Укажите заголовок"},
            }
        ),
    )
    page.goto(f"{e2e_server}/generate")
    expect(page.frame_locator("#livePreviewFrame").locator("body")).to_have_text("Просмотр 1")
    fixtures._generator_step(page, 2)
    with page.expect_response("**/api/generate/live-preview"):
        page.locator("#genBtn").click()
    expect(page.frame_locator("#livePreviewFrame").locator("body")).to_have_text(updates[-1])
    expect(page.locator("#documentOutput")).to_be_hidden()
    expect(page.locator("#documentFields")).to_be_visible()
    expect(page.locator("#field-error-title")).to_have_text("Укажите заголовок")
    expect(page.locator("#field-error-title")).to_be_visible()
    expect(page.locator("#field-title")).to_be_focused()
    expect(page.locator("#field-title")).to_have_attribute("aria-invalid", "true")
    page.locator("#field-title").fill("Исправленный заголовок")
    expect(page.locator("#field-error-title")).to_be_hidden()
    assert page.e2e_errors == []


@pytest.mark.parametrize("width", [375, 706])
def test_narrow_document_view_keeps_form_data(e2e_server: str, page: Page, width: int) -> None:
    """В боковой панели можно сосредоточиться на документе, не потеряв введённые поля."""
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{e2e_server}/generate")
    fixtures._generator_step(page)
    page.locator("#field-title").fill("Документ в узком окне")
    page.get_by_role("button", name="Посмотреть документ", exact=True).click()
    expect(page.locator("#documentFields")).to_be_hidden()
    expect(page.locator("#livePreviewFrame")).to_be_visible()
    expect(page.locator("#preview-title")).to_be_focused()
    page.get_by_role("button", name="Вернуться к форме", exact=True).click()
    expect(page.locator("#field-title")).to_have_value("Документ в узком окне")
    page.get_by_role("button", name="Посмотреть документ", exact=True).click()
    page.locator('[data-generator-step="2"]').click()
    expect(page.locator("#documentOutput")).to_be_visible()
    expect(page.get_by_role("button", name="Посмотреть документ", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.e2e_errors == []
