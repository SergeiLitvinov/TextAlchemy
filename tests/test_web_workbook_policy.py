"""Unsupported workbooks are explained without launching document adapters."""

from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests import test_browser_e2e as browser_fixtures
from tests import test_web_m4_completion as api_fixtures
from textalchemy.convert.executor import infer_format
from textalchemy.convert.input_policy import WORKBOOK_MESSAGE

m4_client = api_fixtures.m4_client
browser, page, e2e_server = browser_fixtures.browser, browser_fixtures.page, browser_fixtures.e2e_server


@pytest.mark.parametrize("suffix", [".xlsx", ".ODS"])
@pytest.mark.parametrize("endpoint,field", [("/api/convert", "file"), ("/api/convert/batch", "files")])
@pytest.mark.parametrize("source", ["auto", "pdf"])
def test_workbook_rejection_precedes_format_override(
    m4_client: Any, suffix: str, endpoint: str, field: str, source: str
) -> None:
    client, store = m4_client
    before = store.list_tasks(limit=None)
    response = client.post(endpoint, files={field: (f"research{suffix}", b"not parsed")},
                           data={"source_format": source, "target_format": "html"})
    assert response.status_code == 400, response.text
    assert WORKBOOK_MESSAGE in response.json()["detail"]
    assert store.list_tasks(limit=None) == before
    with pytest.raises(ValueError, match="XLSX/ODS"):
        infer_format(Path(f"research{suffix}"))


@pytest.mark.parametrize("width,batch", [(375, False), (1280, True)])
def test_browser_explains_workbook_without_submission(e2e_server: str, page: Page, width: int, batch: bool) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{e2e_server}/convert")
    page.wait_for_function("document.querySelector('#fileInput').accept.includes('.txt')")
    submissions = []
    page.on("request", lambda request: submissions.append(request.url)
            if request.method == "POST" and '/api/convert' in request.url else None)
    files = [{"name": "research.XLSX", "mimeType": "application/octet-stream", "buffer": b"not parsed"}]
    if batch:
        files.append({"name": "note.txt", "mimeType": "text/plain", "buffer": b"Note"})
    page.locator('#fileInput').set_input_files(files)
    expect(page.locator('#status')).to_have_text(WORKBOOK_MESSAGE)
    expect(page.locator('#conversionSetup')).to_be_hidden()
    assert submissions == []
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
