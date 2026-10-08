"""Цветовые потери: сохранённая политика, повтор задачи и понятный отчёт Web."""

from pathlib import Path
from typing import Any

import pytest

from tests import test_browser_e2e as browser_fixtures
from tests import test_web_m4_completion as fixtures
from tests.convert.test_color_budget import color_source
from textalchemy.web.queue import task_queue

m4_client = fixtures.m4_client
browser, page, e2e_server = browser_fixtures.browser, browser_fixtures.page, browser_fixtures.e2e_server


@pytest.mark.parametrize("target,limit,accepted", [("html", 0, False), ("html", 1, True), ("docx", 1, False), ("docx", 2, True)])
def test_web_color_budget_and_retry(m4_client: Any, tmp_path: Path, target: str, limit: int, accepted: bool) -> None:
    client, store = m4_client
    source = color_source(tmp_path / "source.json")
    response = client.post(
        "/api/convert",
        files={"file": (source.name, source.read_bytes())},
        data={"target_format": target, "max_loss_issues": str(limit)},
    )
    assert response.status_code == 200, response.text
    created = response.json()
    for cycle in range(2):
        assert task_queue.wait_idle(timeout=30)
        task = store.get(created["task_id"])
        assert task["max_loss_issues"] == limit
        assert task["status"] == ("done" if accepted else "error"), task
        assert task["report"]["metrics"]["quality_gate"]["loss_issues"] == (1 if target == "html" else 2)
        assert client.get(created["result"]).status_code == (200 if accepted else 409)
        if cycle == 0:
            assert client.post(f"/api/tasks/{created['task_id']}/rerun").status_code == 200


@pytest.mark.parametrize("width,strict", [(375, True), (1280, False)])
def test_browser_explains_color_loss_and_keeps_original_diagnostic(
    e2e_server: str,
    page: Any,
    tmp_path: Path,
    width: int,
    strict: bool,
) -> None:
    from axe_core_python.sync_playwright import Axe
    from playwright.sync_api import expect

    source = color_source(tmp_path / "source.json")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/convert")
    browser_fixtures._wait_convert_ready(page)
    page.locator("#fileInput").set_input_files(str(source))
    page.locator("#target").select_option("docx")
    if strict:
        page.locator("#expertConversionBtn").click()
        page.locator(".conversion-loss-budget summary").click()
        page.locator("#maxLossIssues").select_option("0")
    page.locator("#convertBtn").click()
    expect(page.locator("#issueList")).to_contain_text("исходный ICC-профиль не применяется", timeout=60000)
    expect(page.locator("#issueList")).to_contain_text("Перекрывающиеся элементы могут выглядеть иначе")
    profile = page.locator("#issueList li").filter(has=page.get_by_text("Цветовой профиль", exact=True))
    expect(profile.locator(".issue-diagnostic")).not_to_have_attribute("open", "")
    profile.get_by_text("Диагностика обработчика", exact=True).click()
    expect(profile.locator(".issue-diagnostic p")).to_contain_text("Print-profile")
    if strict:
        expect(page.locator("#downloadBtn")).to_be_hidden()
        expect(page.locator("#qualityGateSummary")).to_contain_text("допустимо: 0")
    else:
        expect(page.locator("#downloadBtn")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not [item for item in Axe().run(page)["violations"] if item.get("impact") in ("serious", "critical")]
    assert page.e2e_errors == []
