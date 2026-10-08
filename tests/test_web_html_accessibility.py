"""HTML → модель → HTML: сохранение выбранной семантики и реальная навигация."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests import test_browser_e2e as fixtures
from textalchemy.web.queue import task_queue
from textalchemy.web.tasks import TaskStore

browser, page, e2e_server, task_store = fixtures.browser, fixtures.page, fixtures.e2e_server, fixtures.task_store
SOURCE = Path(__file__).parent / "corpus/html-accessibility.html"


def observe(page: Page, path: Path) -> dict[str, Any]:
    """Снять браузерное свидетельство без второго HTML-парсера в приложении."""
    page.goto(path.resolve().as_uri())
    expect(page.get_by_role("heading", name="Measurement report", level=1)).to_be_visible()
    expect(page.get_by_role("heading", name="Procedure", level=2)).to_be_visible()
    expect(page.get_by_role("listitem")).to_have_count(2)
    expect(page.locator("ol")).to_have_attribute("start", "3")
    link = page.get_by_role("link", name="Go to measurements", exact=True)
    page.keyboard.press("Tab")
    expect(link).to_be_focused()
    page.keyboard.press("Enter")
    expect(page).to_have_url(path.resolve().as_uri() + "#measurements")
    table = page.get_by_role("table")
    expect(table).to_contain_text("12")
    return {
        "title": page.title(),
        "language": page.locator("html").get_attribute("lang"),
        "table_caption_count": page.locator("table > caption").count(),
        "column_headers": page.get_by_role("columnheader").all_text_contents(),
        "row_headers": page.get_by_role("rowheader").all_text_contents(),
        "accessible_table_name": page.get_by_role("table", name="Measurements", exact=True).count(),
        "aria_snapshot": page.locator("body").aria_snapshot(),
        "horizontal_overflow": page.evaluate("document.documentElement.scrollWidth > innerWidth"),
    }


@pytest.mark.parametrize("width", [375, 1280])
def test_web_html_roundtrip_preserves_language_caption_and_header_roles(
    e2e_server: str, page: Page, task_store: TaskStore, tmp_path: Path, width: int
) -> None:
    """Принять исправленный конечный профиль, отдельно от CSS и экранного диктора."""
    from importlib.metadata import version

    page.set_viewport_size({"width": width, "height": 900})
    original = SOURCE.read_bytes()
    source_evidence = observe(page, SOURCE)
    assert source_evidence["language"] == "en"
    assert source_evidence["column_headers"] == ["Sample", "Value"] and source_evidence["row_headers"] == ["A"]
    assert source_evidence["table_caption_count"] == source_evidence["accessible_table_name"] == 1
    observations = []
    with httpx.Client(base_url=e2e_server, timeout=30) as client:
        content = original
        for cycle in range(2):
            imported = client.post(
                "/api/convert", files={"file": ("report.html", content, "text/html")}, data={"target_format": "model"}
            )
            assert imported.status_code == 200, imported.text
            assert task_queue.wait_idle(timeout=30)
            imported_task = imported.json()
            model = client.get(imported_task["result"])
            assert model.status_code == 200
            exported = client.post(
                "/api/convert", files={"file": ("report.json", model.content)},
                data={"target_format": "html", "max_loss_issues": "0"}
            )
            assert exported.status_code == 200, exported.text
            assert task_queue.wait_idle(timeout=30)
            exported_task = exported.json()
            strict_report = client.get(exported_task["status"]).json()["report"]
            if cycle == 1:
                # Повторное чтение CSS самого экспортёра теперь даёт сохраняемый ledger LOSS.
                assert not strict_report["success"]
                assert strict_report["metrics"]["quality_gate"]["loss_issues"] > 0
                assert client.get(exported_task["result"]).status_code == 409
                assert any(issue["feature"] == "html-css" for issue in strict_report["issues"])
                allowed = client.post(
                    "/api/convert", files={"file": ("report.json", model.content)}, data={"target_format": "html"}
                )
                assert allowed.status_code == 200, allowed.text
                assert task_queue.wait_idle(timeout=30)
                exported_task = allowed.json()
            else:
                assert strict_report["success"] and strict_report["metrics"]["quality_gate"]["loss_issues"] == 0
            result = client.get(exported_task["result"])
            assert result.status_code == 200
            output = tmp_path / f"roundtrip-{cycle + 1}.html"
            output.write_bytes(result.content)
            observed = observe(page, output)
            assert observed["language"] == "en"
            assert observed["column_headers"] == ["Sample", "Value"]
            assert observed["row_headers"] == ["A"]
            assert observed["table_caption_count"] == observed["accessible_table_name"] == 1
            report = client.get(exported_task["status"]).json()["report"]
            assert report["success"] and report["lossless"] is (cycle == 0)
            assert any(issue["severity"] == "loss" for issue in report["issues"]) is (cycle == 1)
            assert report["metrics"]["step_metrics"]["model.html"]["html_navigation"]["verified"]
            observations.append({"cycle": cycle + 1, "browser": observed, "report": report, "strict_report": strict_report})
            content = result.content
    evidence = {
        "scope": "chromium_roles_and_keyboard_only",
        "versions": {name: version(name) for name in ("textalchemy", "opendoc-model", "opendoc-formats")},
        "browser_version": page.context.browser.version,
        "viewport_width": width,
        "source": source_evidence,
        "roundtrips": observations,
        "semantic_acceptance": True,
        "screen_reader_acceptance": None,
    }
    (tmp_path / "html-accessibility-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    page.screenshot(path=str(tmp_path / f"html-accessibility-{width}.png"), full_page=True)
    assert SOURCE.read_bytes() == original
    assert page.e2e_errors == []


@pytest.mark.parametrize("width", [375, 1280])
def test_html_result_explains_unverified_semantics_without_fabricated_loss(
    e2e_server: str, page: Page, task_store: TaskStore, tmp_path: Path, width: int
) -> None:
    """Пользователь видит область отчёта, а зарегистрированные потери не выдумываются."""
    from axe_core_python.sync_playwright import Axe

    from textalchemy.core.document_codec import save_document
    from textalchemy.formats.html import read_html_model

    source = tmp_path / "model.json"
    save_document(read_html_model(SOURCE), source)
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/convert")
    fixtures._wait_convert_ready(page)
    page.locator("#fileInput").set_input_files(str(source))
    page.locator("#target").select_option("html")
    expect(page.locator("#routeGuidanceList")).to_contain_text("проверьте язык документа и заголовки таблиц")
    page.locator("#convertBtn").click()
    notice = page.locator("#htmlSemanticsNotice")
    expect(notice).to_be_visible(timeout=60000)
    expect(notice).to_contain_text("не подтверждает доступность")
    expect(page.locator("#qualityBadge")).to_have_text("Потерь не зарегистрировано")
    expect(notice.get_by_role("link", name="Как проверить HTML")).to_have_attribute(
        "href", "/help/doc/guide/conversion/#проверка-html-и-доступности"
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not [item for item in Axe().run(page)["violations"] if item.get("impact") in ("serious", "critical")]
    notice.get_by_role("link", name="Как проверить HTML").click()
    expect(page).to_have_url(e2e_server + "/help/doc/guide/conversion/#" + quote("проверка-html-и-доступности"))
    expect(page.get_by_role("heading", name="Проверка HTML и доступности", exact=True)).to_be_visible()
    assert page.e2e_errors == []


def test_html_diagnostic_opens_source_fragment_from_keyboard(
    e2e_server: str, page: Page, task_store: TaskStore
) -> None:
    """Исходное предупреждение HTML остаётся связано с фрагментом и доступно с клавиатуры."""
    page.goto(e2e_server + "/convert")
    fixtures._wait_convert_ready(page)
    page.locator("#fileInput").set_input_files(str(SOURCE.with_name("html-warnings.html")))
    page.locator("#target").select_option("model")
    page.locator("#convertBtn").click()
    issue = page.locator("#issueList li").filter(has=page.get_by_text("Оформление HTML", exact=True)).filter(
        has_text="background-color"
    )
    expect(issue).to_be_visible(timeout=60000)
    button = issue.get_by_role("button")
    button.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#issueInspector")).to_be_focused()
    expect(page.locator("#issueFragment")).to_contain_text("Абзац с неподдержанным фоном.")
    expect(button).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#htmlSemanticsNotice")).to_be_hidden()
    assert page.e2e_errors == []
