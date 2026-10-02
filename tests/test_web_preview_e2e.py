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
