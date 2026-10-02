"""Emphasis budget through durable tasks, batches and the browser."""

import re

import pytest

from tests import test_browser_e2e as browser_fixtures
from tests import test_web_m4_completion as fixtures
from tests.convert.test_emphasis_quality import emphasis_document
from textalchemy.convert.docx_writer import write_docx_model
from textalchemy.web.queue import task_queue

m4_client = fixtures.m4_client
browser, e2e_server, page = browser_fixtures.browser, browser_fixtures.e2e_server, browser_fixtures.page


@pytest.mark.parametrize('limit,accepted', [(0, False), (4, True)])
def test_web_emphasis_limit_controls_download_and_retry(m4_client, tmp_path, limit, accepted):
    client, store = m4_client
    source = tmp_path / 'source.docx'
    write_docx_model(emphasis_document(), source)
    result = client.post('/api/convert', files={'file': ('source.docx', source.read_bytes())},
                        data={'target_format': 'txt', 'max_changed_emphasis': str(limit)})
    assert result.status_code == 200, result.text
    task_id = result.json()['task_id']
    for cycle in range(2):
        assert task_queue.wait_idle(timeout=30)
        task = store.get(task_id)
        assert task['max_changed_emphasis'] == limit
        assert task['status'] == ('done' if accepted else 'error'), task
        assert task['report']['metrics']['emphasis_quality_gate']['changed_characters'] == 4
        assert client.get(result.json()['result']).status_code == (200 if accepted else 409)
        if cycle == 0:
            assert client.post(f'/api/tasks/{task_id}/rerun').status_code == 200


def test_batch_emphasis_budget_survives_retry(m4_client, tmp_path):
    client, store = m4_client
    source = tmp_path / 'source.docx'
    write_docx_model(emphasis_document(), source)
    result = client.post('/api/convert/batch', files=[('files', ('a.docx', source.read_bytes())),
        ('files', ('b.docx', source.read_bytes()))], data={'target_format': 'txt', 'max_changed_emphasis': '0'})
    assert result.status_code == 200, result.text
    job_id = result.json()['job_id']
    for cycle in range(2):
        assert task_queue.wait_idle(timeout=30)
        job = store.get_job(job_id)
        assert job['max_changed_emphasis'] == 0
        for entry in job['files']:
            task = store.get(entry['task_id'])
            assert task['status'] == 'error' and task['max_changed_emphasis'] == 0
            assert not task.get('artifact')
        if cycle == 0:
            assert client.post(f'/api/convert/jobs/{job_id}/rerun').status_code == 200


@pytest.mark.parametrize('width', [375, 1280])
def test_browser_explains_emphasis_loss_and_blocks_download(e2e_server, page, m4_client, tmp_path, width):
    from axe_core_python.sync_playwright import Axe
    from playwright.sync_api import expect

    source = tmp_path / 'source.docx'
    write_docx_model(emphasis_document(), source)
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(e2e_server + '/convert')
    expect(page.locator('#fileInput')).to_have_attribute('accept', re.compile(r'\.docx'))
    page.locator('#fileInput').set_input_files(str(source))
    page.locator('#expertConversionBtn').click()
    page.locator('summary').filter(has_text='Расширенная проверка сохранности').click()
    page.locator('#maxChangedEmphasis').fill('0')
    page.locator('#target').select_option('txt')
    page.locator('#convertBtn').click()
    expect(page.locator('#emphasisGateSummary')).to_contain_text('выделением: 4; допустимо: 0', timeout=60000)
    expect(page.locator('#downloadBtn')).to_be_hidden()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not [item for item in Axe().run(page)['violations'] if item.get('impact') in ('serious', 'critical')]
    assert page.e2e_errors == []
