"""Переход из приложения в офлайн-руководство, поиск, код и возврат в двух темах."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests import test_browser_e2e as browser_fixtures

browser, e2e_server, page = browser_fixtures.browser, browser_fixtures.e2e_server, browser_fixtures.page


@pytest.mark.parametrize("width", [375, 1280])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_help_from_application_search_code_and_return(e2e_server: str, page: Page, width: int, theme: str) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.emulate_media(color_scheme=theme)
    page.goto(e2e_server + "/generate")
    page.get_by_role("link", name="Открыть руководство", exact=True).click()
    expect(page.locator("#hero-title")).to_contain_text("TextAlchemy")
    expect(page.locator("[data-app-return]")).to_be_visible()
    expect(page.locator("html")).to_have_attribute("data-theme", theme)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator("[data-open-search]").click()
    page.locator("#mkdocs-search-query").fill("распознавание")
    page.locator("#mkdocs-search-query").press("ArrowRight")
    expect(page.locator("#mkdocs-search-results article").first).to_be_visible(timeout=30000)
    page.locator("#mkdocs-search-query").press("Escape")
    if width == 375:
        page.locator(".docs-menu-button").click()
        page.locator("#docs-navigation summary").filter(has_text="Разработка").click()
        page.locator("#docs-navigation").get_by_role("link", name="Навигатор по коду", exact=True).click()
    else:
        page.locator(".docs-top-nav").get_by_role("link", name="Код", exact=True).click()
    expect(page.locator(".docs-prose h1")).to_contain_text("Навигатор")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_role("link", name="Вернуться в программу", exact=True).click()
    expect(page.locator(".welcome-panel")).to_be_visible()
    assert page.e2e_errors == []
