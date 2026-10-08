"""Public DjVu API integration; synthetic API doubles are not engine acceptance."""

from pathlib import Path

import pytest
from opendoc_formats import ImportResult
from opendoc_formats.errors import ExtractError
from opendoc_model import DiagnosticIssue, DocumentModel, Paragraph, Section, TextRun

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest, requirement_available
from textalchemy.core.diagnostics import IssueSeverity
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.types import DocFormat
from textalchemy.web.services.conversion_catalog import available_conversions


def test_missing_djvutxt_is_a_component_not_a_python_module(monkeypatch):
    monkeypatch.setattr('shutil.which', lambda name: None)
    monkeypatch.setattr('locale.getpreferredencoding', lambda _: 'utf-8')
    assert not requirement_available('djvutxt')
    catalog = available_conversions(ConversionExecutor())
    entry = next(item for item in catalog['unavailable_sources'] if item['format'] == 'djvu')
    txt = next(item for item in entry['unavailable_targets'] if item['format'] == 'txt')
    assert txt['unavailable_modes']['balanced']['requirements'] == ['djvutxt']
    assert txt['unavailable_modes']['faithful']['code'] == 'unsupported_mode'


def test_djvu_preflight_accepts_cp1251_with_the_published_adapter(monkeypatch):
    monkeypatch.setattr('shutil.which', lambda _: 'djvutxt')
    monkeypatch.setattr('locale.getpreferredencoding', lambda _: 'cp1251')
    assert ConversionExecutor().plan(DocFormat.DJVU, DocFormat.TXT) is not None
    entry = next(item for item in available_conversions(ConversionExecutor())['sources']
                 if item['format'] == 'djvu')
    txt = next(item for item in entry['targets'] if item['format'] == 'txt')
    assert 'balanced' in txt['modes']


def test_public_djvu_api_is_used_for_repeated_text_export(tmp_path: Path, monkeypatch):
    source, output = tmp_path / 'synthetic.djvu', tmp_path / 'text.txt'
    source.write_bytes(b'API contract double; not a DjVu fixture')
    original = source.read_bytes()
    calls = []

    def read(path, *, format_id):
        calls.append((path, format_id))
        model = DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun(text='Text layer')])])])
        return ImportResult(model, 'djvu', (DiagnosticIssue('import.notice', IssueSeverity.WARNING, 'API notice'),))

    monkeypatch.setattr('opendoc_formats.read_document', read)
    executor = ConversionExecutor(requirement_checker=lambda _: True)
    for _ in range(2):
        report = executor.execute(ConversionRequest(source, output, DocFormat.DJVU, DocFormat.TXT))
        assert report.success, report.to_dict()
        assert output.read_text(encoding='utf-8').strip() == 'Text layer'
        assert report.metrics['executed_steps'] == ['djvu.model', 'model.txt']
        assert report.metrics['step_metrics']['djvu.model']['page_geometry_verified'] is None
        assert {issue.feature for issue in report.issues} >= {'djvu-text-only', 'import.notice'}
    assert calls == [(source, 'djvu'), (source, 'djvu')]
    assert source.read_bytes() == original
    assert executor.plan(DocFormat.DJVU, DocFormat.TXT, mode=ConversionMode.FAITHFUL) is None


@pytest.mark.parametrize('failure', ['empty', 'timeout', 'invalid'])
def test_public_djvu_failure_preserves_previous_result(tmp_path, monkeypatch, failure):
    source, output = tmp_path / 'synthetic.djvu', tmp_path / 'text.txt'
    source.write_bytes(b'API contract double')
    output.write_bytes(b'Previous result')

    def read(*args, **kwargs):
        if failure == 'invalid':
            return ImportResult(None, 'djvu', (DiagnosticIssue('import.invalid-model', IssueSeverity.ERROR, 'Invalid model'),))
        raise ExtractError('djvutxt timeout' if failure == 'timeout' else 'DjVu text extraction returned no content')

    monkeypatch.setattr('opendoc_formats.read_document', read)
    report = ConversionExecutor(requirement_checker=lambda _: True).execute(
        ConversionRequest(source, output, DocFormat.DJVU, DocFormat.TXT))
    assert not report.success
    assert output.read_bytes() == b'Previous result'
