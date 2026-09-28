"""Actual PDF vector-loss diagnostics resolve to stable source block IDs."""
import copy
import importlib

import fitz
import pytest
from fastapi.testclient import TestClient

from textalchemy.web.services import pdf_order
from textalchemy.web.services.pdf_diagnostics import attach_targets
from textalchemy.web.tasks import TaskStore


def make_warning_pdf():
    pdf = fitz.open()
    pdf.new_page().insert_text((70, 150), 'First page')
    page = pdf.new_page()
    page.insert_text((70, 150), 'Before vector')
    page.draw_rect(fitz.Rect(70, 220, 250, 320), color=(1, 0, 0))
    content = pdf.tobytes()
    pdf.close()
    return content


def test_actual_diagnostics_follow_reordered_block(tmp_path, monkeypatch):
    web = importlib.import_module('textalchemy.web.app')
    parent = TaskStore(tmp_path / 'tasks')
    monkeypatch.setattr(web, 'tasks_store', parent)
    with TestClient(web.app) as client:
        response = client.post('/api/pdf-order', files={'file': ('warning.pdf', make_warning_pdf())})
        assert response.status_code == 200
        draft = response.json()
        url = '/api/pdf-order/' + draft['draft_id']
        store = pdf_order.store_for(parent)
        before = pdf_order.load(store, draft['draft_id'])
        report = client.get(url + '/diagnostics?revision=1')
        assert report.status_code == 200
        warning = next(i for i in report.json()['issues'] if i['feature'] == 'image' and i['target'])
        block_id = warning['target']['block_id']
        assert warning['target']['page'] == 1
        assert 'Vector drawing' in warning['target']['label']
        assert pdf_order.load(store, draft['draft_id']) == before  # A check does not mutate the draft or refresh TTL.
        order = copy.deepcopy(before['order'])
        order[1].reverse()
        assert client.put(url, json={'revision': 1, 'order': order}).status_code == 200
        report2 = client.get(url + '/diagnostics?revision=2').json()
        warning2 = next(i for i in report2['issues'] if i['feature'] == 'image' and i['target'])
        assert warning2['target']['block_id'] == block_id
        assert warning2['location'] != warning['location']
        assert client.get(url + '/diagnostics?revision=1').status_code == 409
        assert client.get(url + '/diagnostics').status_code == 422
        assert client.get('/api/pdf-order/missing/diagnostics?revision=1').status_code == 404


@pytest.mark.parametrize('location', ['', 'resources[0]', 'sections[99].blocks[0]', 'sections[0].blocks[99]',
                                     'sections[0].headers[0]', 'sections[0].blocks[0]garbage', '<script>'])
def test_unresolved_location_has_no_navigation(location):
    from textalchemy.core.document_codec import document_to_dict
    from textalchemy.core.document_model import DocumentModel, Paragraph, Section

    value = {'revision': 1, 'order': [['stable-id']],
             'model': document_to_dict(DocumentModel(sections=[Section(blocks=[Paragraph()])]))}
    report = {'success': True, 'issues': [{'location': location, 'message': 'warning'}]}
    assert attach_targets(value, report)['issues'][0]['target'] is None
