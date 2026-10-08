"""Opt-in browser acceptance with real EasyOCR and local prepared models."""

import hashlib
import json
import os
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests import test_browser_e2e as fixtures
from tests.corpus.ocr_fixture import LINES, write_printed_page
from textalchemy.recognize import OcrEngine

browser, page, e2e_server, task_store = fixtures.browser, fixtures.page, fixtures.e2e_server, fixtures.task_store

pytestmark = pytest.mark.skipif(
    os.environ.get('TEXTALCHEMY_EASYOCR_ACCEPTANCE') != '1', reason='Native EasyOCR acceptance is opt-in',
)


@pytest.mark.parametrize('format_id,width', [('png', 375), ('pdf', 1280)])
def test_native_ocr_browser_upload_edit_download_reload(e2e_server, page, task_store, tmp_path, monkeypatch,
                                                      format_id, width):
    from axe_core_python.sync_playwright import Axe

    source = write_printed_page(tmp_path / 'printed.png', Path(os.environ['TEXTALCHEMY_OCR_TEST_FONT']))
    pages = 1
    if format_id == 'pdf':
        import fitz  # Independent raster-only QA fixture, never application parsing.

        raster = source.read_bytes()
        source = tmp_path / 'scanned.pdf'
        with fitz.open() as document:
            for _ in range(2):
                document.new_page(width=500, height=180).insert_image(fitz.Rect(0, 0, 500, 180), stream=raster)
            document.save(source)
        pages = 2
    original = source.read_bytes()

    def forbid_network(*args, **kwargs):
        raise AssertionError('Native OCR must use local prepared models')

    monkeypatch.setattr(urllib.request, 'urlopen', forbid_network)
    assert OcrEngine().backend_name == 'easyocr'
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(e2e_server + '/recognize')
    expect(page.locator('#processBtn')).to_be_disabled()
    page.locator('#fileInput').set_input_files(source)
    expect(page.locator('#selectedFile')).to_contain_text(source.name)
    expect(page.locator('#resultEmpty')).to_be_visible()
    if format_id == 'pdf':
        page.locator('#scenario').select_option('scan')
    else:
        expect(page.locator('#scenarioOptions')).to_be_hidden()
    page.locator('#processBtn').focus()
    page.keyboard.press('Enter')
    expect(page.locator('#result')).to_be_visible(timeout=90000)
    recognized = page.locator('#result').input_value()
    normalize = lambda text: ''.join(text.casefold().split())  # noqa: E731
    assert normalize(recognized) == normalize('\n'.join(LINES) * pages)
    expect(page.locator('#processBtn')).to_be_enabled()
    expect(page.locator('#resultSource')).to_have_text(source.name)
    assert 'draft=' in page.url
    corrected = recognized + '\nCorrected 012'
    page.locator('#result').fill(corrected)
    expect(page.locator('#editStatus')).to_contain_text('несохранённые правки')
    page.locator('#saveTextBtn').click()
    expect(page.locator('#editStatus')).to_have_text('Текст сохранён')
    page.reload()
    expect(page.locator('#result')).to_have_value(corrected, timeout=30000)
    page.locator('#ocrExportFormat').select_option('txt')
    with page.expect_download() as pending:
        page.locator('#exportTextBtn').click()
    download = pending.value
    assert download.suggested_filename == 'corrected.txt'
    assert download.path().read_text(encoding='utf-8').rstrip('\n') == corrected
    expect(page.locator('#status')).to_contain_text('отправлен на скачивание')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not [item for item in Axe().run(page)['violations'] if item.get('impact') in ('serious', 'critical')]
    page.screenshot(path=str(tmp_path / 'ocr-browser.png'), full_page=True)
    assert page.e2e_errors == []
    assert source.read_bytes() == original
    (tmp_path / 'browser-evidence.json').write_text(json.dumps({
        'engine': 'easyocr', 'format': format_id, 'pages': pages, 'viewport_width': width,
        'browser': page.context.browser.version, 'source_sha256': hashlib.sha256(original).hexdigest(),
        'recognized_text': recognized, 'saved_text': corrected,
        'scope': 'Own raster, real HTTP and browser upload/edit/reload/download; no arbitrary scan acceptance',
    }, ensure_ascii=False, indent=2), encoding='utf-8')
