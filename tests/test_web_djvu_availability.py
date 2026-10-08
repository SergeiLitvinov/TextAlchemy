"""Real browser explains missing DjVu component without starting conversion."""

import pytest
from playwright.sync_api import expect

from tests import test_browser_e2e as fixtures
from tests import test_web_m4_completion as api_fixtures

browser, page, e2e_server = fixtures.browser, fixtures.page, fixtures.e2e_server
m4_client = api_fixtures.m4_client


@pytest.mark.parametrize('endpoint,field', [('/api/convert', 'file'), ('/api/convert/batch', 'files')])
def test_missing_djvutxt_rejects_submission_without_saved_tasks(m4_client, monkeypatch, endpoint, field):
    monkeypatch.setattr('shutil.which', lambda _: None)
    client, store = m4_client
    before = store.list_tasks(limit=None)
    response = client.post(endpoint, files={field: ('source.djvu', b'not parsed')}, data={'target_format': 'txt'})
    assert response.status_code == 400
    assert 'djvutxt' in response.json()['detail']
    assert store.list_tasks(limit=None) == before


def test_missing_djvu_component_is_visible_before_upload(e2e_server, page):
    page.set_viewport_size({'width': 375, 'height': 900})
    page.goto(f'{e2e_server}/convert')
    capabilities = page.request.get(f'{e2e_server}/api/convert/capabilities').json()
    # The test is about UI handling, independent of the machine's optional DjVu installation.
    unavailable = {'format': 'djvu', 'label': 'DjVu', 'extensions': ['.djvu'], 'targets': [],
                   'unavailable_targets': [{'format': 'txt', 'unavailable_modes': {
                       'balanced': {'code': 'missing_dependencies', 'requirements': ['djvutxt'],
                                    'message': 'Для маршрута не найдены компоненты: djvutxt.'}}}]}
    capabilities['sources'] = [item for item in capabilities['sources'] if item['format'] != 'djvu']
    capabilities['unavailable_sources'] = [unavailable]
    page.route('**/api/convert/capabilities', lambda route: route.fulfill(json=capabilities))
    page.reload()
    page.wait_for_function("document.querySelector('#fileInput').accept.includes('.txt')")
    requests = []
    page.on('request', lambda request: requests.append(request.url)
            if request.method == 'POST' and '/api/convert' in request.url else None)
    page.locator('#fileInput').set_input_files({
        'name': 'scan.djvu', 'mimeType': 'application/octet-stream', 'buffer': b'not parsed',
    })
    expect(page.locator('#status')).to_contain_text('djvutxt')
    expect(page.locator('#conversionSetup')).to_be_hidden()
    assert not requests
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
