"""Real browser and DjVuLibre text-layer acceptance; no mocked format API."""

import hashlib
import json
import locale
import subprocess
import sys
from importlib.metadata import version

import pytest
from playwright.sync_api import expect

from tests import test_browser_e2e as fixtures
from tests.convert import test_djvu_real as engine_fixtures
from tests.corpus.djvu_fixture import PAGE_TEXT, make_djvu

browser, page, e2e_server, task_store = fixtures.browser, fixtures.page, fixtures.e2e_server, fixtures.task_store
djvu_tools = engine_fixtures.djvu_tools


@pytest.mark.parametrize('width', [375, 1280])
def test_browser_real_djvu_text_route_twice(e2e_server, page, task_store, tmp_path, width, djvu_tools):
    source = make_djvu(tmp_path / 'source')
    original = source.read_bytes()
    evidence = {'source_sha256': hashlib.sha256(original).hexdigest(), 'width': width,
                'opendoc-formats': version('opendoc-formats'), 'opendoc-model': version('opendoc-model'),
                'page_geometry_verified': None, 'cycles': [],
                'python': sys.version.split()[0], 'process_encoding': locale.getpreferredencoding(False),
                'chromium': page.context.browser.version,
                'djvulibre': subprocess.run(['djvused', '-help'], capture_output=True, text=True,
                                            timeout=10).stderr.splitlines()[0]}
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(f'{e2e_server}/convert')
    page.wait_for_function("document.querySelector('#fileInput').accept.includes('.djvu')")
    for cycle in range(2):
        page.locator('#fileInput').set_input_files(source)
        expect(page.locator('#sourceFilename')).to_have_text(source.name)
        assert page.locator('#sourceFilename').bounding_box()['width'] > 80
        assert page.evaluate('''() => {
            const label = document.querySelector('#sourceBadge').getBoundingClientRect();
            const button = document.querySelector('#replaceBtn').getBoundingClientRect();
            return label.right <= button.left || label.bottom <= button.top;
        }''')
        expect(page.locator('#target')).to_have_value('txt')
        expect(page.locator('#routeGuidanceList')).to_contain_text('текстовый слой')
        with page.expect_response(lambda response: response.url.endswith('/api/convert')
                                  and response.request.method == 'POST') as submitted:
            page.locator('#convertBtn').click()
        created = submitted.value.json()
        expect(page.locator('#resultCard')).to_be_visible(timeout=30000)
        expect(page.locator('#downloadBtn')).to_be_visible()
        expect(page.locator('#issueList')).to_contain_text('Страницы, координаты, изображения')
        with page.expect_download() as downloaded:
            page.locator('#downloadBtn').click()
        output = tmp_path / f'cycle-{cycle + 1}.txt'
        downloaded.value.save_as(output)
        text = output.read_text(encoding='utf-8')
        assert all(value in text for value in PAGE_TEXT)
        assert text.index(PAGE_TEXT[0]) < text.index(PAGE_TEXT[1])
        task = task_store.get(created['task_id'])
        assert task['status'] == 'done', task
        evidence['cycles'].append({'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                                   'report': task['report']})
        if cycle == 0:
            page.locator('#anotherBtn').click()
    assert source.read_bytes() == original
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    (tmp_path / 'djvu-evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    page.screenshot(path=str(tmp_path / 'djvu-result.png'), full_page=True)
    assert page.e2e_errors == []
