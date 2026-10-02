"""Переход по нативной ссылке DOCX в реально экспортированном HTML."""

import pytest
from playwright.sync_api import expect

from tests import test_browser_e2e as fixtures
from tests.convert.test_html_normalize import build_bookmark_docx
from textalchemy.convert.html_writer import write_html_model
from textalchemy.formats.docx import read_docx_model

browser, page = fixtures.browser, fixtures.page


@pytest.mark.parametrize("width", [375, 1280])
def test_word_bookmark_link_navigates_to_inline_target(page, tmp_path, width):
    source = build_bookmark_docx(tmp_path / "source.docx")
    output = tmp_path / "result.html"
    report = write_html_model(read_docx_model(source), output)
    assert report.success and report.metrics["html_navigation"]["verified"]
    page.set_viewport_size({"width": width, "height": 600})
    page.goto(output.as_uri())
    link = page.get_by_role("link", name="Jump to target")
    expect(link).to_have_attribute("href", "#target_section")
    link.click()
    assert page.url.endswith("#target_section")
    assert page.evaluate("scrollY") > 0
    bounds = page.locator("#target_section").bounding_box()
    assert 0 <= bounds["y"] <= 600
    target = page.locator("#target_section").evaluate("el => el.nextSibling.textContent")
    assert target == "Target text"
    assert page.e2e_errors == []
