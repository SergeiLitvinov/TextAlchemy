"""Permanent datasets survive reopen and reject stale or incompatible writes."""
import copy
import importlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from textalchemy.web.services.generator_datasets import DatasetStore


@pytest.fixture
def dataset_client(tmp_path, monkeypatch):
    web = importlib.import_module('textalchemy.web.app')
    monkeypatch.setattr(web, 'data_dir', tmp_path)
    with TestClient(web.app) as client:
        template = client.get('/api/generate/templates').json()[0]['name']
        schema = client.get(f'/api/generate/templates/{template}/schema').json()['schema']
        snapshot = {'version': 1, 'schema': json.dumps(schema), 'output': 'saved.docx', 'format': 'docx',
                    'values': [{'name': field['name'], 'value': False if field.get('type') == 'boolean' else 'Saved value'}
                               for field in schema['fields']]}
        yield client, {'template': template, 'name': 'Research', 'snapshot': snapshot}, tmp_path


def test_create_reload_update_and_name_collision(dataset_client):
    client, payload, root = dataset_client
    created = client.post('/api/generate/datasets', json=payload)
    assert created.status_code == 200, created.text
    item = created.json()
    url = '/api/generate/datasets/' + item['id']
    assert DatasetStore(root).get(item['id'])['snapshot'] == payload['snapshot']
    assert client.get('/api/generate/datasets', params={'template': payload['template']}).json()[0]['id'] == item['id']
    assert client.get('/api/generate/datasets', params={'template': 'other'}).json() == []
    assert client.post('/api/generate/datasets', json={**payload, 'name': ' research '}).status_code == 409
    changed = copy.deepcopy(payload)
    changed['snapshot']['output'] = 'revised.docx'
    assert client.put(url, json={**changed, 'revision': 1}).json()['revision'] == 2
    assert client.put(url, json={**payload, 'revision': 1}).status_code == 409
    assert client.get(url).json()['snapshot']['output'] == 'revised.docx'


def test_concurrent_updates_have_one_winner(dataset_client):
    client, payload, _ = dataset_client
    item = client.post('/api/generate/datasets', json=payload).json()
    url = '/api/generate/datasets/' + item['id']
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda name: client.put(url, json={**payload, 'name': name, 'revision': 1}), ['One', 'Two']))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert client.get(url).json()['revision'] == 2


@pytest.mark.parametrize('problem', ['schema', 'field', 'missing', 'format', 'large', 'name'])
def test_invalid_dataset_preserves_saved_version(dataset_client, problem):
    client, payload, _ = dataset_client
    item = client.post('/api/generate/datasets', json=payload).json()
    url = '/api/generate/datasets/' + item['id']
    changed = copy.deepcopy(payload)
    if problem == 'schema':
        changed['snapshot']['schema'] = '{}'
    elif problem == 'field':
        changed['snapshot']['values'][0]['value'] = {'bad': 'value'}
    elif problem == 'missing':
        changed['snapshot']['values'] = []
    elif problem == 'format':
        changed['snapshot']['format'] = 'exe'
    elif problem == 'large':
        changed['snapshot']['output'] = 'x' * (5 * 1024 * 1024)
    else:
        changed['name'] = '   '
    assert client.put(url, json={**changed, 'revision': 1}).status_code == (409 if problem == 'schema' else 422)
    assert client.get(url).json()['snapshot'] == payload['snapshot']


def test_storage_failure_and_schema_change(dataset_client, monkeypatch):
    client, payload, root = dataset_client
    item = client.post('/api/generate/datasets', json=payload).json()
    url = '/api/generate/datasets/' + item['id']

    def fail(*args, **kwargs):
        raise OSError('disk unavailable')

    with monkeypatch.context() as patch:
        patch.setattr(DatasetStore, 'save', fail)
        assert client.put(url, json={**payload, 'revision': 1}).status_code == 503
    from textalchemy.generate.template_schema import TemplateSchema

    monkeypatch.setattr('textalchemy.web.routes.generate.template_schema_for',
                        lambda name: (TemplateSchema(fields=[]), 'derived'))
    assert client.get(url).status_code == 409
    assert DatasetStore(root).get(item['id'])['snapshot'] == payload['snapshot']
