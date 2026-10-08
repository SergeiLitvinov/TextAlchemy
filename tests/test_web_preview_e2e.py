"""Настоящие страницы PDF в Web и независимость сервера от медленного рендера."""

from __future__ import annotations

import concurrent.futures
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, Route, expect

from tests import test_browser_e2e as fixtures
from tests.test_web_preview_services import pdf
from textalchemy.web.routes import convert as facade
from textalchemy.web.routes import convert_preview
from textalchemy.web.tasks import TaskStore

browser, page, e2e_server, task_store = fixtures.browser, fixtures.page, fixtures.e2e_server, fixtures.task_store


def open_saved_preview(page: Page, server: str) -> None:
    """Открыть настоящие сохранённые PDF через историю конвертации."""
    page.goto(server + "/convert")
    fixtures._wait_convert_ready(page)
    page.locator("#conversionHistory > summary").click()
    page.locator("#historyList details summary").click()
    page.locator('[data-preview-task="pages"]').click()
    expect(page.locator("#previewSection")).to_be_visible()


def test_unknown_structure_and_absent_objects_are_not_percentages(
    e2e_server: str,
    page: Page,
    task_store: TaskStore,
    tmp_path: Path,
) -> None:
    """Неизвестная метрика, отсутствие объектов и измеренный ноль различаются."""
    seed(task_store, tmp_path)
    comparison = {
        "retention": {
            "pages": {"source": None, "target": 2, "ratio": None},
            "images": {"source": 0, "target": 0, "ratio": 1},
            "characters": {"source": 10, "target": 0, "ratio": 0},
        }
    }
    task_store.set("pages", {**task_store.get("pages"), "comparison": comparison})
    open_saved_preview(page, e2e_server)
    page.locator("#comparisonSection > summary").click()
    grid = page.locator("#retentionGrid")
    unknown = grid.locator(".retention-item").filter(has=page.get_by_text("Страницы", exact=True))
    absent = grid.locator(".retention-item").filter(has=page.get_by_text("Изображения", exact=True))
    lost = grid.locator(".retention-item").filter(has=page.get_by_text("Текст", exact=True))
    expect(unknown.locator("strong")).to_have_text("Не измерено")
    expect(absent.locator("strong")).to_have_text("Нет в исходнике")
    expect(lost.locator("strong")).to_have_text("0%")
    expect(lost).to_have_class("retention-item bad")
    expect(unknown).to_have_class("retention-item")
    expect(absent).to_have_class("retention-item")
    expect(page.locator("#comparisonMessage")).to_contain_text("Часть структуры не измерена")
    assert task_store.get("pages")["comparison"] == comparison
    assert page.e2e_errors == []


@pytest.mark.parametrize("header,expected", [(None, None), ("", None), ("invalid", None), ("1.2", None), ("0", "0%")])
def test_visual_measurement_missing_header_is_unknown_and_zero_is_measured(
    e2e_server: str,
    page: Page,
    task_store: TaskStore,
    tmp_path: Path,
    header: str | None,
    expected: str | None,
) -> None:
    """Отсутствующий показатель не заменяется нулём при получении карты различий."""
    seed(task_store, tmp_path)

    def alter_header(route: Route) -> None:
        response = route.fetch()
        headers = {key: value for key, value in response.headers.items() if key.lower() != "x-visual-similarity"}
        if header is not None:
            headers["X-Visual-Similarity"] = header
        route.fulfill(response=response, headers=headers)

    page.route("**/preview/pages/diff?*", alter_header)
    open_saved_preview(page, e2e_server)
    page.locator("#previewModeDiff").click()
    page.wait_for_function("document.querySelector('#previewCanvas img')?.naturalWidth > 0")
    hint = page.locator("#previewHint")
    if expected is None:
        expect(hint).to_contain_text("не измерено")
        expect(hint).not_to_contain_text("0%")
    else:
        expect(hint).to_contain_text(expected)
        expect(hint).to_contain_text("110 dpi")
        expect(hint).to_contain_text("не оценка всего документа")
    assert page.e2e_errors == []


def test_failed_next_page_clears_previous_visual_measurement(
    e2e_server: str,
    page: Page,
    task_store: TaskStore,
    tmp_path: Path,
) -> None:
    seed(task_store, tmp_path)
    open_saved_preview(page, e2e_server)
    page.locator("#previewModeDiff").click()
    expect(page.locator("#previewHint")).to_contain_text("110 dpi")
    expect(page.locator("#previewHint")).to_contain_text("%")
    page.route("**/preview/pages/diff?page=2&*", lambda route: route.fulfill(status=404, body="Comparison unavailable"))
    page.locator("#previewNext").click()
    expect(page.locator("#previewHint")).to_contain_text("сравнение недоступно")
    expect(page.locator("#previewHint")).not_to_contain_text("%")
    assert page.e2e_errors == ["Failed to load resource: the server responded with a status of 404 (Not Found)"]


def seed(store: TaskStore, tmp_path: Path, task_id: str = "pages", *, pages: int = 2) -> None:
    source, target = tmp_path / f"{task_id}-source.pdf", tmp_path / f"{task_id}-target.pdf"
    pdf(source, "Original", pages=pages)
    pdf(target, "Converted", pages=pages)
    store.store_source(task_id, source, source.name)
    artifact = store.store_artifact(task_id, target, target.name)
    store.set(
        task_id,
        {
            "status": "done",
            "queue_kind": "convert",
            "artifact": artifact,
            "filename": target.name,
            "media_type": "application/pdf",
            "source_format": "pdf",
            "target_format": "pdf",
            "mode": "balanced",
        },
    )
    store.set_job(
        f"preview-{task_id}",
        {
            "job_id": f"preview-{task_id}",
            "mode": "balanced",
            "target_format": "pdf",
            "files": [
                {
                    "task_id": task_id,
                    "name": source.name,
                    "source_format": "pdf",
                    "target_format": "pdf",
                    "mode": "balanced",
                    "result": f"/api/convert/result/{task_id}",
                },
            ],
        },
    )


@pytest.mark.parametrize("width", [375, 1280])
def test_visual_evidence_in_report_after_reopening(
    e2e_server: str, page: Page, task_store: TaskStore, tmp_path: Path, width: int
) -> None:
    """Измерение настоящих PDF отображается и сохраняется при повторном открытии отчёта."""
    seed(task_store, tmp_path)
    page.set_viewport_size({"width": width, "height": 900})
    task_store.set("pages", {**task_store.get("pages"), "report": {"issues": [], "metrics": {"executed_steps": ["pdf.pdf"]}}})
    original = task_store.get("pages")
    open_saved_preview(page, e2e_server)
    expect(page.locator("#visualEvidence")).to_be_hidden()
    page.locator("#previewModeDiff").click()
    expect(page.locator("#visualEvidence")).to_be_visible()
    page.locator("#visualEvidence > summary").click()
    expect(page.locator("#visualEvidenceList")).to_contain_text("Страница 1:")
    expect(page.locator("#visualEvidenceList")).to_contain_text("110 dpi")
    expect(page.locator("#visualEvidenceList")).to_contain_text("opendoc-model")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    with httpx.Client(base_url=e2e_server) as client:
        payload = client.get("/api/convert/status/pages").json()
    assert payload["report"]["metrics"]["executed_steps"] == ["pdf.pdf"]
    records = payload["report"]["metrics"]["visual_measurements"]
    assert len(records) == 1 and records[0]["page"] == 1 and records[0]["editability_verified"] is None
    assert task_store.get("pages") == original
    open_saved_preview(page, e2e_server)
    expect(page.locator("#visualEvidence")).to_be_visible()
    page.locator("#visualEvidence > summary").click()
    expect(page.locator("#visualEvidenceList")).to_contain_text("Страница 1:")
    assert page.e2e_errors == []


@pytest.mark.parametrize("width", [375, 1280])
def test_saved_pdf_preview_source_target_compare_diff_and_keyboard(
    e2e_server: str, page: Page, task_store: TaskStore, tmp_path: Path, width: int
) -> None:
    seed(task_store, tmp_path)
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/convert")
    fixtures._wait_convert_ready(page)
    if not page.locator("#conversionHistory").evaluate("el => el.open"):
        page.locator("#conversionHistory > summary").click()
    page.locator("#historyList details summary").click()
    page.locator('[data-preview-task="pages"]').click()
    expect(page.locator("#previewSection")).to_be_visible()
    page.wait_for_function("document.querySelector('#previewCanvas img')?.naturalWidth > 0")
    expect(page.locator("#previewPageLabel")).to_have_text("1 / 2")
    page.locator("#previewCanvas").focus()
    page.keyboard.press("ArrowRight")
    expect(page.locator("#previewPageLabel")).to_have_text("2 / 2")
    page.wait_for_function("document.querySelector('#previewCanvas img')?.naturalWidth > 0")
    page.locator("#previewModeTarget").click()
    expect(page.locator("#previewCanvas figcaption")).to_have_text("Результат")
    page.wait_for_function("document.querySelector('#previewCanvas img')?.naturalWidth > 0")
    page.locator("#previewModeCompare").click()
    expect(page.locator("#previewCanvas img")).to_have_count(2)
    page.wait_for_function("Array.from(document.querySelectorAll('#previewCanvas img')).every(img => img.naturalWidth > 0)")
    page.locator("#previewModeDiff").click()
    expect(page.locator("#previewHint")).to_contain_text("Визуальное сходство страницы")
    page.wait_for_function("document.querySelector('#previewCanvas img')?.naturalWidth > 0")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator("#previewSection").scroll_into_view_if_needed()
    page.screenshot(path=str(tmp_path / f"pdf-preview-{width}.png"))
    assert page.e2e_errors == []


@pytest.mark.parametrize("delayed", ["status", "meta"])
def test_late_previous_task_does_not_replace_selected_preview(
    e2e_server: str, page: Page, task_store: TaskStore, tmp_path: Path, delayed: str
) -> None:
    seed(task_store, tmp_path, "slow", pages=1)
    seed(task_store, tmp_path, "current", pages=3)
    held: list[Route] = []
    endpoint = "/api/convert/status/slow" if delayed == "status" else "/api/convert/preview/slow/meta"
    page.route("**" + endpoint, lambda route: held.append(route))
    page.goto(e2e_server + "/convert")
    fixtures._wait_convert_ready(page)
    if not page.locator("#conversionHistory").evaluate("el => el.open"):
        page.locator("#conversionHistory > summary").click()
    for summary in page.locator("#historyList details summary").all():
        summary.click()
    with page.expect_request("**" + endpoint):
        page.locator('[data-preview-task="slow"]').click()
    page.locator('[data-preview-task="current"]').click()
    expect(page.locator("#previewPageLabel")).to_have_text("1 / 3")
    assert len(held) == 1
    with page.expect_response("**" + endpoint):
        held[0].fulfill(response=held[0].fetch())
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    expect(page.locator("#previewPageLabel")).to_have_text("1 / 3")
    expect(page.locator("#previewSection")).to_be_visible()
    assert page.e2e_errors == []


def test_preview_revalidates_pages_cached_by_previous_app_version(
    e2e_server: str, page: Page, task_store: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(task_store, tmp_path)
    respond = convert_preview._image_response

    def old_cache_policy(image: convert_preview.PreviewImage) -> convert_preview.Response:
        response = respond(image)
        response.headers["Cache-Control"] = "private, max-age=3600"
        return response

    monkeypatch.setattr(convert_preview, "_image_response", old_cache_policy)
    page.goto(e2e_server + "/convert")
    fixtures._wait_convert_ready(page)
    if not page.locator("#conversionHistory").evaluate("el => el.open"):
        page.locator("#conversionHistory > summary").click()
    page.locator("#historyList details summary").click()
    page.locator('[data-preview-task="pages"]').click()
    page.wait_for_function("document.querySelector('#previewCanvas img')?.naturalWidth > 0")
    url = e2e_server + "/api/convert/preview/pages?side=target&page=1&dpi=110"
    with page.expect_response(url) as first:
        page.locator("#previewModeTarget").click()
    original = first.value.body()
    assert first.value.headers["cache-control"] == "private, max-age=3600"
    page.locator("#previewModeSource").click()
    page.wait_for_function("document.querySelector('#previewCanvas img')?.naturalWidth > 0")
    replacement = tmp_path / "replacement.pdf"
    pdf(replacement, "New saved result")
    task = task_store.get("pages")
    task_store.store_artifact("pages", replacement, task["artifact"])
    task_store.set("pages", {**task, "revision": 2})
    with page.expect_response(url) as refreshed:
        page.locator("#previewModeTarget").click()
    assert refreshed.value.body() != original
    page.wait_for_function("document.querySelector('#previewCanvas img')?.naturalWidth > 0")
    assert page.e2e_errors == []


@pytest.mark.parametrize("operation", ["meta", "page", "inspect"])
def test_conversion_render_and_inspection_do_not_block_web(
    e2e_server: str, task_store: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    seed(task_store, tmp_path)
    entered, release = threading.Event(), threading.Event()

    def blocked(*_args: Any, **_kwargs: Any) -> Any:
        entered.set()
        assert release.wait(timeout=10)
        if operation == "inspect":
            raise ValueError("inspection failed")
        return 2 if operation == "meta" else b"png image"

    backend = {"meta": "cached_page_count", "page": "cached_page_png", "inspect": "inspect_path"}[operation]
    monkeypatch.setattr(facade, backend, blocked)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        if operation == "inspect":
            pending = executor.submit(
                httpx.post, e2e_server + "/api/convert/inspect", files={"file": ("source.txt", b"text")}, timeout=15
            )
        else:
            endpoint = "/meta" if operation == "meta" else ""
            pending = executor.submit(httpx.get, e2e_server + "/api/convert/preview/pages" + endpoint, timeout=15)
        try:
            assert entered.wait(timeout=5)
            healthy = httpx.get(e2e_server + "/api/tasks", timeout=3)
            assert healthy.status_code == 200 and not release.is_set()
        finally:
            release.set()
        assert pending.result(timeout=15).status_code == (400 if operation == "inspect" else 200)
