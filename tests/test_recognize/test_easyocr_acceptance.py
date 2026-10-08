"""Opt-in real EasyOCR weights, CPU execution and application geometry contract."""

import hashlib
import json
import math
import os
import urllib.request
from importlib.metadata import version
from pathlib import Path

import pytest

from tests.corpus.ocr_fixture import LINES, write_printed_page
from textalchemy.recognize import OcrEngine

pytestmark = pytest.mark.skipif(
    os.environ.get('TEXTALCHEMY_EASYOCR_ACCEPTANCE') != '1', reason='Native EasyOCR acceptance is opt-in',
)


@pytest.mark.parametrize('handwriting', [False, True], ids=['printed', 'sensitivity-preset'])
def test_real_easyocr_default_languages_and_geometry(tmp_path, monkeypatch, handwriting):
    # Weights are prepared separately from inference, never downloaded inside the test.
    model_root = Path(os.environ['EASYOCR_MODULE_PATH']) / 'model'
    for filename, expected in (
        ('craft_mlt_25k.pth', '2f8227d2def4037cdb3b34389dcf9ec1'),
        ('cyrillic_g2.pth', '19f85f43d9128a89ac21b8d6a06973fe'),
    ):
        assert hashlib.md5((model_root / filename).read_bytes()).hexdigest() == expected
    font = Path(os.environ['TEXTALCHEMY_OCR_TEST_FONT'])
    source = write_printed_page(tmp_path / 'printed.png', font)
    original = source.read_bytes()

    def forbid_network(*args, **kwargs):
        raise AssertionError('Native inference must use prepared local models')

    monkeypatch.setattr(urllib.request, 'urlopen', forbid_network)
    engine = OcrEngine(backend='easyocr', use_gpu=False)
    assert engine.is_available and engine.backend_name == 'easyocr'
    plain = engine.recognize(source, handwriting=handwriting)
    geometry = engine.recognize_with_geometry(source, scale=2, handwriting=handwriting)
    assert plain.language == 'rus,eng'
    normalize = lambda text: ''.join(text.casefold().split())  # noqa: E731 - local comparison projection
    for text in (plain.text, '\n'.join(block.text for block in geometry.blocks)):
        positions = [normalize(text).index(normalize(line)) for line in LINES]
        assert positions == sorted(positions)
    assert 0 < plain.confidence <= 1 and math.isfinite(plain.confidence)
    assert geometry.blocks
    for block in geometry.blocks:
        x0, y0, x1, y1 = block.bbox
        assert 0 <= x0 < x1 <= 500 and 0 <= y0 < y1 <= 180
        assert 0 < block.confidence <= 1 and math.isfinite(block.confidence)
    assert source.read_bytes() == original
    evidence = {
        'engine': 'easyocr', 'device': 'cpu', 'versions': {name: version(name) for name in ('easyocr', 'torch', 'torchvision')},
        'handwriting_preset': handwriting, 'scope': 'Own printed raster; not handwriting or arbitrary scan acceptance',
        'source_sha256': hashlib.sha256(original).hexdigest(), 'font_sha256': hashlib.sha256(font.read_bytes()).hexdigest(),
        'text': plain.text, 'confidence': plain.confidence,
        'blocks': [{'text': block.text, 'bbox': block.bbox, 'confidence': block.confidence} for block in geometry.blocks],
    }
    (tmp_path / 'easyocr-evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')


def test_real_easyocr_cli_recognizes_and_exports_text(tmp_path, monkeypatch, capsys):
    from textalchemy.__main__ import main

    source = write_printed_page(tmp_path / 'printed.png', Path(os.environ['TEXTALCHEMY_OCR_TEST_FONT']))
    original = source.read_bytes()
    output = tmp_path / 'recognized.txt'
    output.write_text('Previous result', encoding='utf-8')

    def forbid_network(*args, **kwargs):
        raise AssertionError('CLI inference must use prepared local models')

    monkeypatch.setattr(urllib.request, 'urlopen', forbid_network)
    assert main(['recognize', str(source), '--backend', 'easyocr', '--lang', 'rus+eng',
                 '--output', str(output), '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    text = output.read_text(encoding='utf-8')
    assert text.splitlines() == list(LINES)
    assert report == {'saved': str(output), 'pages': 1, 'length': len(text)}
    assert source.read_bytes() == original
    (tmp_path / 'cli-evidence.json').write_text(json.dumps({
        'engine': 'easyocr', 'device': 'cpu', 'report': report,
        'source_sha256': hashlib.sha256(original).hexdigest(),
        'result_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'text': text, 'scope': 'Own printed raster through CLI and published text writer',
    }, ensure_ascii=False, indent=2), encoding='utf-8')
