"""Published DOCX preservation and opaque-object budget through actual Web tasks."""

import pytest

from tests import test_web_m4_completion as api_fixtures
from tests.test_docx_layout_acceptance import BUILDERS, first_row_widths, native_text, smart_tag_xml
from textalchemy.web.queue import task_queue

m4_client = api_fixtures.m4_client


def converted(client, content, name, target, limit):
    started = client.post('/api/convert', files={'file': (name, content)},
                          data={'target_format': target, 'max_loss_issues': str(limit)})
    assert started.status_code == 200, started.text
    assert task_queue.wait_idle(timeout=30)
    task = started.json()
    status = client.get(task['status']).json()
    return status['report'], client.get(task['result'])


@pytest.mark.parametrize('case,limit', [('percentage-table', 0), ('smart-tag', 1)])
def test_docx_layout_web_two_cycles_preserve_selected_properties(m4_client, tmp_path, case, limit):
    client, _store = m4_client
    source = tmp_path / 'source.docx'
    BUILDERS[case](source)
    original = source.read_bytes()
    content = original
    for cycle in (1, 2):
        imported, model = converted(client, content, 'source.docx', 'model', limit)
        assert imported['success'] and model.status_code == 200
        exported, output = converted(client, model.content, 'model.json', 'docx', limit)
        assert exported['success'] and output.status_code == 200
        result = tmp_path / f'cycle-{cycle}.docx'
        result.write_bytes(output.content)
        assert native_text(result) == native_text(source)
        if case == 'percentage-table':
            assert first_row_widths(result) == first_row_widths(source)
        else:
            assert smart_tag_xml(result) == smart_tag_xml(source)
            for report in (imported, exported):
                assert report['metrics']['quality_gate']['loss_issues'] == 1
                assert any(issue['feature'] == 'docx.smart-tags' and issue['severity'] == 'loss'
                           for issue in report['issues'])
        content = output.content
    assert source.read_bytes() == original


def test_web_smart_tag_zero_budget_exposes_diagnostic_without_result(m4_client, tmp_path):
    client, _store = m4_client
    source = tmp_path / 'source.docx'
    BUILDERS['smart-tag'](source)
    report, output = converted(client, source.read_bytes(), 'source.docx', 'model', 0)
    assert not report['success'] and output.status_code == 409
    assert report['metrics']['quality_gate']['accepted'] is False
    assert any(issue['feature'] == 'docx.smart-tags' and issue['location'] for issue in report['issues'])
