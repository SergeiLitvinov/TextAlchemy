"""Real heading budget survives HTTP, batch retry and browser interactions."""

import pytest
from opendoc_model import save_document
from playwright.sync_api import expect

from tests import test_browser_e2e as browser_fixtures
from tests import test_web_m4_completion as api_fixtures
from tests.convert.test_heading_budget import heading_model
from textalchemy.web.queue import task_queue

m4_client = api_fixtures.m4_client
browser, page, e2e_server, task_store = (
    browser_fixtures.browser, browser_fixtures.page, browser_fixtures.e2e_server, browser_fixtures.task_store,
)


@pytest.mark.parametrize('limit,accepted', [(0, False), (1, True)])
def test_http_heading_budget_and_rerun(m4_client, tmp_path, limit, accepted):
    client, store = m4_client
    source = save_document(heading_model(), tmp_path / 'source.json')
    response = client.post('/api/convert', files={'file': (source.name, source.read_bytes())},
                           data={'target_format': 'txt', 'max_changed_headings': limit})
    assert response.status_code == 200, response.text
    created = response.json()
    for cycle in range(2):
        assert task_queue.wait_idle(timeout=30)
        task = store.get(created['task_id'])
        assert task['max_changed_headings'] == limit
        assert task['status'] == ('done' if accepted else 'error'), task
        assert task['report']['metrics']['heading_quality_gate']['changed_headings'] == 1
        result = client.get(created['result'])
        assert result.status_code == (200 if accepted else 409)
        if cycle == 0:
            assert client.post(f"/api/tasks/{created['task_id']}/rerun").status_code == 200


def test_batch_heading_budget_and_selective_retry(m4_client, tmp_path):
    client, store = m4_client
    source = save_document(heading_model(), tmp_path / 'source.json')
    response = client.post('/api/convert/batch', files=[
        ('files', ('source.json', source.read_bytes())), ('files', ('plain.txt', b'Plain body')),
    ], data={'target_format': 'txt', 'max_changed_headings': 0})
    assert response.status_code == 200, response.text
    created = response.json()
    bad_id, good_id = [item['task_id'] for item in created['tasks']]
    assert task_queue.wait_idle(timeout=30)
    assert store.get(bad_id)['status'] == 'error'
    good = store.get(good_id)
    assert good['status'] == 'done'
    result = store.result_path(good_id, good['artifact']).read_bytes()
    retry = client.post(f"/api/convert/jobs/{created['job_id']}/rerun", data={'failed_only': 'true'})
    assert retry.status_code == 200 and retry.json()['launched'] == [bad_id]
    assert task_queue.wait_idle(timeout=30)
    assert store.get(bad_id)['max_changed_headings'] == 0
    assert store.get(bad_id)['status'] == 'error'
    assert store.get(good_id) == good
    assert store.result_path(good_id, good['artifact']).read_bytes() == result


@pytest.mark.parametrize('endpoint,field', [('/api/convert', 'file'), ('/api/convert/batch', 'files')])
def test_negative_heading_budget_rejected_before_task_creation(m4_client, endpoint, field):
    client, store = m4_client
    before = store.list_tasks(limit=None)
    response = client.post(endpoint, files={field: ('source.txt', b'Body')}, data={'max_changed_headings': -1})
    assert response.status_code == 422
    assert store.list_tasks(limit=None) == before


@pytest.mark.parametrize('width,limit', [(375, 0), (1280, 1)])
def test_browser_heading_budget_explains_result(e2e_server, page, task_store, tmp_path, width, limit):
    source = save_document(heading_model(), tmp_path / 'source.json')
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(f'{e2e_server}/convert')
    page.wait_for_function("document.querySelector('#fileInput').accept.includes('.json')")
    page.locator('#fileInput').set_input_files(source)
    page.locator('#expertConversionBtn').click()
    page.locator('.conversion-loss-budget summary').click()
    page.locator('#target').select_option('txt')
    page.locator('#maxChangedHeadings').fill(str(limit))
    page.locator('#convertBtn').click()
    expect(page.locator('#resultCard')).to_be_visible(timeout=30000)
    expect(page.locator('#headingGateSummary')).to_contain_text('заголовков: 1; допустимо:')
    expect(page.locator('#headingGateSummary')).to_contain_text('Результат не выдан.' if limit == 0 else 'Допуск соблюдён.')
    if limit == 0:
        expect(page.locator('#downloadBtn')).to_be_hidden()
    else:
        expect(page.locator('#downloadBtn')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.e2e_errors == []


def test_simple_mode_removes_hidden_heading_gate(e2e_server, page, task_store, tmp_path):
    source = save_document(heading_model(), tmp_path / 'source.json')
    page.goto(f'{e2e_server}/convert')
    page.wait_for_function("document.querySelector('#fileInput').accept.includes('.json')")
    page.locator('#fileInput').set_input_files(source)
    page.locator('#expertConversionBtn').click()
    page.locator('.conversion-loss-budget summary').click()
    page.locator('#maxChangedHeadings').fill('0')
    page.locator('#simpleConversionBtn').click()
    page.locator('#target').select_option('txt')
    page.locator('#convertBtn').click()
    expect(page.locator('#downloadBtn')).to_be_visible(timeout=30000)
    task = next(item for item in task_store.list_tasks(limit=None) if item.get('source_name') == 'source.json')
    assert task['status'] == 'done' and task['max_changed_headings'] is None
    assert 'heading_quality_gate' not in task['report']['metrics']
    assert page.e2e_errors == []
