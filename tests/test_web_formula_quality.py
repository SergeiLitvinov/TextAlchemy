"""Formula budgets survive durable Web tasks, batches, retries and publication."""

import re

import pytest

from tests import test_browser_e2e as browser_fixtures
from tests import test_web_m4_completion as fixtures
from tests.convert.test_formula_quality import MATH, source_document
from textalchemy.web.queue import task_queue

m4_client = fixtures.m4_client
browser, e2e_server, page = browser_fixtures.browser, browser_fixtures.e2e_server, browser_fixtures.page


@pytest.mark.parametrize('limit, accepted', [(0, False), (1, True)])
def test_web_formula_change_controls_download(m4_client, tmp_path, monkeypatch, limit, accepted):
    from textalchemy.convert.docx_writer import write_docx_model

    client, store = m4_client
    source = source_document(tmp_path)

    def change_formula(model, output):
        model.sections[0].blocks[0].content[-1].value = MATH.replace('<mn>2</mn>', '<mn>3</mn>')
        return write_docx_model(model, output)

    monkeypatch.setattr('textalchemy.convert.executor._write_docx', change_formula)
    response = client.post('/api/convert', files={'file': ('source.json', source.read_bytes())},
                           data={'target_format': 'docx', 'max_changed_formulas': str(limit)})
    assert response.status_code == 200, response.text
    assert task_queue.wait_idle(timeout=30)
    created = response.json()
    task = store.get(created['task_id'])
    assert task['max_changed_formulas'] == limit
    assert task['status'] == ('done' if accepted else 'error'), task
    gate = task['report']['metrics']['formula_quality_gate']
    assert gate['changed_formulas'] == 1 and gate['accepted'] is accepted
    assert client.get(created['result']).status_code == (200 if accepted else 409)
    assert bool(task.get('artifact')) is accepted


def test_batch_formula_budget_survives_full_retry(m4_client, tmp_path):
    client, store = m4_client
    content = source_document(tmp_path).read_bytes()
    response = client.post('/api/convert/batch', files=[
        ('files', ('first.json', content)), ('files', ('second.json', content)),
    ], data={'target_format': 'docx', 'max_changed_formulas': '0'})
    assert response.status_code == 200, response.text
    batch = response.json()
    for cycle in range(2):
        assert task_queue.wait_idle(timeout=30)
        job = store.get_job(batch['job_id'])
        assert job['max_changed_formulas'] == 0
        for entry in job['files']:
            task = store.get(entry['task_id'])
            assert task['status'] == 'done' and task['max_changed_formulas'] == 0
            assert task['report']['metrics']['formula_quality_gate']['changed_formulas'] == 0
        if cycle == 0:
            retried = client.post(f"/api/convert/jobs/{batch['job_id']}/rerun")
            assert retried.status_code == 200, retried.text


@pytest.mark.parametrize('width', [375, 1280])
def test_web_formula_budget_can_be_selected_and_explained(e2e_server, page, m4_client, tmp_path, width):
    from axe_core_python.sync_playwright import Axe
    from playwright.sync_api import expect

    page.set_viewport_size({'width': width, 'height': 900})
    # An old unversioned module in the browser cache must not break the new page.
    page.route('**/static/js/pages/convert/quality.js', lambda route: route.fulfill(
        status=200, content_type='text/javascript', body='export const obsolete = true;',
    ))
    page.goto(e2e_server + '/convert')
    expect(page.locator('#fileInput')).to_have_attribute('accept', re.compile(r'\.json'))
    page.locator('#fileInput').set_input_files({'name': 'source.json', 'mimeType': 'application/json',
                                             'buffer': source_document(tmp_path).read_bytes()})
    page.locator('#expertConversionBtn').click()
    page.locator('summary').filter(has_text='Расширенная проверка сохранности').click()
    page.locator('#maxChangedFormulas').fill('0')
    page.locator('#target').select_option('docx')
    page.locator('#convertBtn').click()
    expect(page.locator('#formulaGateSummary')).to_contain_text('Допуск соблюдён', timeout=60000)
    expect(page.locator('#formulaGateSummary')).to_contain_text('формул: 0; допустимо: 0')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    violations = [item for item in Axe().run(page)['violations'] if item.get('impact') in ('serious', 'critical')]
    assert not violations, violations
    assert page.e2e_errors == []
