"""Real DjVuLibre corpus acceptance, separate from API doubles."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.corpus.djvu_fixture import PAGE_TEXT, make_djvu
from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.types import DocFormat


@pytest.fixture
def djvu_tools():
    missing = [name for name in ('c44', 'djvused', 'djvm', 'djvutxt') if shutil.which(name) is None]
    if missing:
        pytest.skip('Real DjVu acceptance needs ' + ', '.join(missing))


def test_real_unicode_djvu_repeated_export(tmp_path: Path, djvu_tools):
    source = make_djvu(tmp_path / 'source')
    original = source.read_bytes()
    output = tmp_path / 'result.txt'
    for _ in range(2):
        report = ConversionExecutor().execute(ConversionRequest(source, output, DocFormat.DJVU, DocFormat.TXT))
        assert report.success, report.to_dict()
        content = output.read_text(encoding='utf-8')
        for text in PAGE_TEXT:
            assert text in content
        assert content.index(PAGE_TEXT[0]) < content.index(PAGE_TEXT[1])
        assert any(issue.feature == 'djvu-text-only' for issue in report.issues)
    assert source.read_bytes() == original


def test_real_djvu_without_text_preserves_previous_result(tmp_path: Path, djvu_tools):
    source = make_djvu(tmp_path / 'source', with_text=False)
    output = tmp_path / 'result.txt'
    output.write_bytes(b'Previous result')
    report = ConversionExecutor().execute(ConversionRequest(source, output, DocFormat.DJVU, DocFormat.TXT))
    assert not report.success, report.to_dict()
    assert output.read_bytes() == b'Previous result'


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows cp1251 process acceptance')
def test_real_djvu_windows_cp1251_without_utf8_mode(tmp_path, djvu_tools):
    source = make_djvu(tmp_path / 'unicode')
    empty = make_djvu(tmp_path / 'empty', with_text=False)
    originals = {path: path.read_bytes() for path in (source, empty)}
    script = r'''
import json, locale, sys
from pathlib import Path
from opendoc_formats import read_document
from opendoc_formats.errors import ExtractError
from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.types import DocFormat
source, empty, output = map(Path, sys.argv[1:])
assert sys.flags.utf8_mode == 0
assert locale.getpreferredencoding(False).lower() == 'cp1251'
cycles = []
for _ in range(2):
    result = ConversionExecutor().execute(ConversionRequest(source, output, DocFormat.DJVU, DocFormat.TXT))
    assert result.success, result.to_dict()
    cycles.append(output.read_text(encoding='utf-8'))
output.write_bytes(b'Previous result')
result = ConversionExecutor().execute(ConversionRequest(empty, output, DocFormat.DJVU, DocFormat.TXT))
assert not result.success and output.read_bytes() == b'Previous result'
try:
    read_document(empty, format_id='djvu')
except ExtractError as error:
    assert 'text layer' in str(error)
else:
    raise AssertionError('Empty hidden text must not produce a successful model')
print(json.dumps({'encoding': locale.getpreferredencoding(False), 'cycles': cycles}))
'''
    completed = subprocess.run(
        [sys.executable, '-X', 'utf8=0', '-c', script, str(source), str(empty), str(tmp_path / 'result.txt')],
        env={**os.environ, 'PYTHONUTF8': '0'}, capture_output=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr.decode('utf-8', errors='replace')
    evidence = json.loads(completed.stdout)
    assert evidence['encoding'] == 'cp1251'
    assert evidence['cycles'][0] == evidence['cycles'][1]
    for text in evidence['cycles']:
        assert all(value in text for value in PAGE_TEXT)
        assert text.index(PAGE_TEXT[0]) < text.index(PAGE_TEXT[1])
    assert all(path.read_bytes() == original for path, original in originals.items())
