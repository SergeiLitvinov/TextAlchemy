"""Opt-in native OCR through Web upload, persisted editing and public exports."""

import hashlib
import json
import os
import urllib.request
from pathlib import Path

import pytest

from tests.corpus.ocr_fixture import LINES, write_printed_page
from tests.test_web_m4_completion import m4_client as m4_client
from textalchemy.core.document_codec import document_from_dict
from textalchemy.recognize import OcrEngine

pytestmark = pytest.mark.skipif(
    os.environ.get('TEXTALCHEMY_EASYOCR_ACCEPTANCE') != '1', reason='Native EasyOCR acceptance is opt-in',
)


@pytest.mark.parametrize('format_id', ['png', 'pdf'])
def test_real_web_ocr_upload_edit_reload_export(m4_client, tmp_path, monkeypatch, format_id):
    client, _store = m4_client
    source = write_printed_page(tmp_path / 'printed.png', Path(os.environ['TEXTALCHEMY_OCR_TEST_FONT']))
    expected_pages = 1
    if format_id == 'pdf':
        import fitz  # Native fixture generation only; application uses published format APIs.

        raster = source.read_bytes()
        source = tmp_path / 'scanned.pdf'
        with fitz.open() as document:
            for _ in range(2):
                page = document.new_page(width=500, height=180)
                page.insert_image(page.rect, stream=raster)
            document.save(source)
        expected_pages = 2
    original = source.read_bytes()

    def forbid_network(*args, **kwargs):
        raise AssertionError('Web inference must use prepared local models')

    monkeypatch.setattr(urllib.request, 'urlopen', forbid_network)
    # No engine substitution: this profile has no external Tesseract executable.
    assert OcrEngine().backend_name == 'easyocr'
    response = client.post('/api/recognize', files={'file': (source.name, original)},
                           data={'lang': 'rus+eng', 'gpu': 'false', 'mode': 'printed', 'scenario': 'scan'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['success'], result
    assert result['backend'] == 'easyocr'
    normalize = lambda text: ''.join(text.casefold().split())  # noqa: E731
    assert normalize(result['text']) == normalize('\n'.join(LINES) * expected_pages)
    if format_id == 'pdf':
        assert result['pages'] == expected_pages
    route = f"/api/recognize/drafts/{result['draft_id']}"
    reloaded = client.get(route).json()
    assert reloaded['text'] == result['text'] and reloaded['revision'] == 1
    corrected = result['text'] + '\nCorrected 012'
    saved = client.put(route, json={'text': corrected, 'revision': 1})
    assert saved.status_code == 200, saved.text
    assert saved.json()['revision'] == 2
    assert client.get(route).json()['text'] == corrected
    assert client.put(route, json={'text': 'Stale edit', 'revision': 1}).status_code == 409
    assert client.get(route + '/export', params={'revision': 1, 'format': 'txt'}).status_code == 409
    exported = client.get(route + '/export', params={'revision': 2, 'format': 'txt'})
    assert exported.status_code == 200, exported.text
    assert exported.content.decode('utf-8').rstrip('\n') == corrected
    model = client.get(route + '/export', params={'revision': 2, 'format': 'model'})
    assert model.status_code == 200
    restored = document_from_dict(model.json())
    assert restored.metadata['scope'] == 'plain-text'
    assert '\n'.join(block.plain_text for section in restored.sections for block in section.blocks) == corrected
    assert source.read_bytes() == original
    (tmp_path / 'web-ocr-evidence.json').write_text(json.dumps({
        'format': format_id, 'engine': result['backend'], 'pages': expected_pages,
        'source_sha256': hashlib.sha256(original).hexdigest(), 'recognized_text': result['text'],
        'saved_revision': 2, 'export_sha256': hashlib.sha256(exported.content).hexdigest(),
        'scope': 'Own raster through Web ASGI, persisted editing and TXT/JSON exports; no browser UI acceptance',
    }, ensure_ascii=False, indent=2), encoding='utf-8')
