"""Bounded table edits against a generated ruled PDF, including actual DOCX export."""
import copy
import importlib
import io

import fitz
import pytest
from fastapi.testclient import TestClient

from textalchemy.web.services import pdf_order
from textalchemy.web.tasks import TaskStore


def make_table_pdf():
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((70, 100), 'Outside table')
    for c in range(4):
        page.draw_line((70 + c * 100, 150), (70 + c * 100, 270))
    for r in range(4):
        page.draw_line((70, 150 + r * 40), (370, 150 + r * 40))
    for r in range(3):
        for c in range(3):
            page.insert_text((80 + c * 100, 175 + r * 40), f'R{r + 1}C{c + 1}')
    page = pdf.new_page()
    page.insert_text((70, 150), 'Other page')
    data = pdf.tobytes()
    pdf.close()
    return data


@pytest.fixture
def table_draft(tmp_path, monkeypatch):
    web = importlib.import_module('textalchemy.web.app')
    parent = TaskStore(tmp_path / 'tasks')
    monkeypatch.setattr(web, 'tasks_store', parent)
    with TestClient(web.app) as client:
        result = client.post('/api/pdf-order', files={'file': ('grid.pdf', make_table_pdf(), 'application/pdf')})
        assert result.status_code == 200, result.text
        data = result.json()
        table = next(block for block in data['pages'][0]['blocks'] if block['table'])
        assert table['table']['cells'] == [[f'R{r}C{c}' for c in range(1, 4)] for r in range(1, 4)]
        yield client, '/api/pdf-order/' + data['draft_id'], pdf_order.store_for(parent), data, table


def test_crop_and_restore_source_table(table_draft):
    from docx import Document

    client, url, store, data, table = table_draft
    before = pdf_order.load(store, data['draft_id'])
    order = copy.deepcopy(before['order'])
    table_id = table['id']
    index = order[0].index(table_id)
    cropped = client.put(url, json={'revision': 1, 'order': order, 'table_ranges': {table_id: [2, 3, 1, 2]}})
    assert cropped.status_code == 200, cropped.text
    after = pdf_order.load(TaskStore(store.root), data['draft_id'])
    model = after['model']
    current = model['document']['sections'][0]['blocks'][index]
    original = before['model']['document']['sections'][0]['blocks'][index]
    assert current['rows'] == [{**row, 'cells': row['cells'][:2]} for row in original['rows'][1:]]
    assert current['box'] == {'x': 70, 'y': 190, 'width': 200, 'height': 80, 'rotation': 0}
    expected = copy.deepcopy(before['model'])
    expected['document']['sections'][0]['blocks'][index] = current
    assert model == expected  # All other blocks, pages, resources and properties unchanged.
    assert client.get(url + '/export?revision=2&format=model').json() == model
    result = client.get(url + '/export?revision=2&format=docx')
    assert result.status_code == 200
    docx = Document(io.BytesIO(result.content))
    assert [[c.text for c in row.cells] for row in docx.tables[0].rows] == [['R2C1', 'R2C2'], ['R3C1', 'R3C2']]
    # The source table is retained outside the export and can be restored after reopening.
    restored = client.get(url).json()
    entry = next(b for b in restored['pages'][0]['blocks'] if b['id'] == table_id)
    assert entry['table']['rows'] == 3
    assert entry['table']['range'] == [2, 3, 1, 2]
    assert client.put(url, json={'revision': 1, 'order': order, 'table_ranges': {table_id: [1, 3, 1, 3]}}).status_code == 409
    assert client.put(url, json={'revision': 2, 'order': order, 'table_ranges': {table_id: [1, 3, 1, 3]}}).status_code == 200
    assert client.get(url + '/export?revision=3&format=model').json() == before['model']


@pytest.mark.parametrize('bounds', [[0, 2, 1, 2], [2, 1, 1, 2], [1, 4, 1, 3], [1, 3, 2, 1],
                                   [1, 3, 1], [True, 3, 1, 3], [1.5, 3, 1, 3], ['1', 3, 1, 3]])
def test_invalid_bounds_are_atomic(table_draft, bounds):
    client, url, store, data, table = table_draft
    before = pdf_order.load(store, data['draft_id'])
    order = copy.deepcopy(before['order'])
    order[0].reverse()
    assert client.put(url, json={'revision': 1, 'order': order, 'table_ranges': {table['id']: bounds}}).status_code == 422
    assert pdf_order.load(store, data['draft_id']) == before


def test_unknown_or_non_table_target_is_atomic(table_draft):
    client, url, store, data, table = table_draft
    before = pdf_order.load(store, data['draft_id'])
    non_table = next(b['id'] for b in data['pages'][0]['blocks'] if b['classifiable'])
    for target in ('unknown', non_table):
        response = client.put(url, json={'revision': 1, 'order': before['order'],
                                        'table_ranges': {table['id']: [2, 3, 1, 2], target: [1, 1, 1, 1]}})
        assert response.status_code == 422
        assert pdf_order.load(store, data['draft_id']) == before


@pytest.mark.parametrize('problem', ['merged', 'irregular'])
def test_unsupported_table_geometry_is_not_editable(table_draft, problem):
    client, url, store, data, table = table_draft
    value = pdf_order.load(store, data['draft_id'])
    index = value['order'][0].index(table['id'])
    block = value['model']['document']['sections'][0]['blocks'][index]
    if problem == 'merged':
        block['rows'][0]['cells'][0]['column_span'] = 2
    else:
        block['properties']['pdf']['cell_bboxes'][0][0] += 10
    store.set(data['draft_id'], value)
    before = pdf_order.load(store, data['draft_id'])
    summary = client.get(url).json()
    assert next(b for b in summary['pages'][0]['blocks'] if b['id'] == table['id'])['table'] is None
    assert client.put(url, json={'revision': 1, 'order': before['order'],
                                 'table_ranges': {table['id']: [2, 3, 1, 2]}}).status_code == 422
    assert pdf_order.load(store, data['draft_id']) == before


def test_failed_table_write_keeps_original(table_draft, monkeypatch):
    client, url, store, data, table = table_draft
    before = pdf_order.load(store, data['draft_id'])

    def fail(*args, **kwargs):
        raise OSError('disk unavailable')

    monkeypatch.setattr(TaskStore, 'set', fail)
    assert client.put(url, json={'revision': 1, 'order': before['order'],
                                 'table_ranges': {table['id']: [2, 3, 1, 2]}}).status_code == 503
    assert pdf_order.load(store, data['draft_id']) == before
