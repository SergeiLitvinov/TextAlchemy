"""Настоящая замена SVG в PDF: понятная потеря, политика и повтор задачи."""

from pathlib import Path
from typing import Any

import pytest

from tests import test_browser_e2e as browser_fixtures
from tests import test_web_m4_completion as fixtures
from tests.convert.test_pdf_resources import SVG
from textalchemy.core.document_codec import save_document
from textalchemy.core.document_model import DocumentModel, Image, Resource, ResourceKind, Section
from textalchemy.web.queue import task_queue

m4_client = fixtures.m4_client
browser, page, e2e_server = browser_fixtures.browser, browser_fixtures.page, browser_fixtures.e2e_server


def vector_source(path: Path) -> Path:
    """Создать разрешённую синтетическую модель с одним SVG."""
    save_document(
        DocumentModel(
            resources={"vector": Resource("vector", ResourceKind.VECTOR_IMAGE, "image/svg+xml", data=SVG)},
            sections=[Section(blocks=[Image("vector", "Красный прямоугольник")])],
        ),
        path,
    )
    return path


@pytest.mark.parametrize("limit", [0, 1])
def test_svg_replacement_diagnostic_and_budget_survive_retry(m4_client: Any, tmp_path: Path, limit: int) -> None:
    """API сохраняет библиотечное свидетельство, не обещая векторную правку."""
    client, store = m4_client
    source = vector_source(tmp_path / "vector.json")
    original = source.read_bytes()
    response = client.post(
        "/api/convert",
        files={"file": (source.name, original)},
        data={"target_format": "pdf", "max_loss_issues": str(limit)},
    )
    assert response.status_code == 200, response.text
    created = response.json()
    for cycle in range(2):
        assert task_queue.wait_idle(timeout=30)
        task = store.get(created["task_id"])
        assert task["status"] == ("done" if limit else "error"), task
        assert task["max_loss_issues"] == limit
        payload = client.get(created["status"]).json()
        issue = next(issue for issue in payload["report"]["issues"] if issue["feature"] == "image-vector")
        assert issue["severity"] == "loss" and "vector" in issue["message"] and "editability is lost" in issue["message"]
        assert issue["location"] == ""  # библиотека не предоставляет связь с объектом для этой потери
        assert payload["report"]["metrics"]["quality_gate"]["loss_issues"] == 1
        result = client.get(created["result"])
        assert result.status_code == (200 if limit else 409)
        if limit:
            assert result.content.startswith(b"%PDF")
        if cycle == 0:
            assert client.post(f"/api/tasks/{created['task_id']}/rerun").status_code == 200
    assert source.read_bytes() == original


@pytest.mark.parametrize("width,strict", [(375, True), (1280, False)])
def test_browser_explains_svg_replacement_and_preserves_evidence(
    e2e_server: str, page: Any, tmp_path: Path, width: int, strict: bool
) -> None:
    """На двух ширинах растр явно отличается от редактируемого вектора."""
    from axe_core_python.sync_playwright import Axe
    from playwright.sync_api import expect

    source = vector_source(tmp_path / "vector.json")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/convert")
    browser_fixtures._wait_convert_ready(page)
    page.locator("#fileInput").set_input_files(str(source))
    page.locator("#target").select_option("pdf")
    if strict:
        page.locator("#expertConversionBtn").click()
        page.locator(".conversion-loss-budget summary").click()
        page.locator("#maxLossIssues").select_option("0")
    page.locator("#convertBtn").click()
    expect(page.locator("#issueList")).to_contain_text("SVG заменён изображением PNG", timeout=60000)
    issue = page.locator("#issueList li").filter(has=page.get_by_text("Векторное изображение", exact=True))
    expect(issue).to_contain_text("Векторные элементы нельзя редактировать по отдельности")
    expect(issue.locator(".issue-diagnostic")).not_to_have_attribute("open", "")
    issue.get_by_text("Диагностика обработчика", exact=True).click()
    expect(issue.locator(".issue-diagnostic p")).to_contain_text("SVG resource 'vector' rasterized")
    expect(page.locator("#downloadBtn")).to_be_hidden() if strict else expect(page.locator("#downloadBtn")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not [item for item in Axe().run(page)["violations"] if item.get("impact") in ("serious", "critical")]
    assert page.e2e_errors == []
