"""Тесты OCR-подсистемы.

Покрывают логику выбора бэкенда, фасад ``OcrEngine`` и разбор результатов
всех трёх бэкендов (tesseract/easyocr/paddle) без реальных OCR-моделей —
внешние библиотеки подменяются фейками через ``sys.modules``.
"""
from __future__ import annotations

import builtins
import sys

import pytest

from textalchemy.core.exceptions import RecognizeError
from textalchemy.formats.pdf_ocr_types import OcrBlockGeometry, OcrPageResult
from textalchemy.recognize import OcrEngine
from textalchemy.recognize.ocr import _merge_word_blocks


# --------------------------------------------------------------------------- #
# Вспомогательные фейки бэкендов
# --------------------------------------------------------------------------- #
def _make_image(tmp_path):
    from PIL import Image

    path = tmp_path / "page.png"
    Image.new("RGB", (200, 100), "white").save(path)
    return path


def _install_pytesseract(monkeypatch):
    import types

    class Output:
        DICT = "dict"

    module = types.ModuleType("pytesseract")
    module.Output = Output
    module.get_tesseract_version = lambda: "5.0"

    def image_to_data(img, lang=None, output_type=None):
        return {
            "text": ["", "Привет", "", "мир"],
            "conf": ["-1", "95", "-1", "88"],
            "left": [0, 10, 0, 90],
            "top": [0, 20, 0, 20],
            "width": [0, 60, 0, 40],
            "height": [0, 30, 0, 30],
            "level": [1, 5, 1, 5],
        }

    module.image_to_data = image_to_data
    module.image_to_string = lambda img, lang=None: "Привет мир"
    monkeypatch.setitem(sys.modules, "pytesseract", module)


def _install_easyocr(monkeypatch, results=None):
    import types

    results = results or [([[10, 20], [60, 20], [60, 50], [10, 50]], "Hello", 0.9)]

    class Reader:
        def __init__(self, languages, gpu=False):
            self.languages = languages
            self.gpu = gpu

        def readtext(self, image, **kwargs):
            return results

    module = types.ModuleType("easyocr")
    module.Reader = Reader
    monkeypatch.setitem(sys.modules, "easyocr", module)


def _install_paddle(monkeypatch):
    import types

    class PaddleOCR:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def predict(self, path):
            return [
                [
                    {"text": "привет", "confidence": 0.9, "box": [[10, 20], [60, 20], [60, 50], [10, 50]]},
                    {"text": "мир", "confidence": 0.8},
                ]
            ]

    module = types.ModuleType("paddleocr")
    module.PaddleOCR = PaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", module)


def _make_available_engine(backend: str) -> OcrEngine:
    engine = OcrEngine()
    engine._backend = backend
    engine._available = True
    return engine


# --------------------------------------------------------------------------- #
# Базовые тесты и выбор бэкенда
# --------------------------------------------------------------------------- #
def test_ocr_engine_init():
    engine = OcrEngine(languages=["rus", "eng"])
    assert engine.languages == ["rus", "eng"]


def test_ocr_engine_init_with_gpu():
    engine = OcrEngine(languages=["rus", "eng"], use_gpu=True)
    assert engine.use_gpu is True


def test_ocr_recognize_no_file():
    engine = OcrEngine()
    with pytest.raises(RecognizeError):
        engine.recognize("nonexistent.png")


def test_ocr_recognize_no_file_handwriting():
    engine = OcrEngine()
    with pytest.raises(RecognizeError):
        engine.recognize("nonexistent.png", handwriting=True)


def test_ocr_backend_auto():
    engine = OcrEngine()
    assert engine.backend_name in (None, "tesseract", "easyocr", "paddle")


def test_ocr_recognize_pdf_no_file():
    engine = OcrEngine()
    with pytest.raises(RecognizeError):
        engine.recognize_pdf("nonexistent.pdf")


def test_ocr_recognize_pdf_no_file_handwriting():
    engine = OcrEngine()
    with pytest.raises(RecognizeError):
        engine.recognize_pdf("nonexistent.pdf", handwriting=True)


def test_auto_detection_prefers_first_available(monkeypatch):
    engine = OcrEngine.__new__(OcrEngine)
    engine.languages = ["rus"]
    engine.use_gpu = False
    monkeypatch.setattr(engine, "_check_tesseract", lambda: False)
    monkeypatch.setattr(engine, "_check_easyocr", lambda: True)
    monkeypatch.setattr(engine, "_check_paddle", lambda: True)
    engine._init_backend("auto")
    assert engine.backend_name == "easyocr"
    assert engine.is_available is True


def test_auto_detection_no_backend(monkeypatch):
    engine = OcrEngine.__new__(OcrEngine)
    engine.languages = ["rus"]
    engine.use_gpu = False
    monkeypatch.setattr(engine, "_check_tesseract", lambda: False)
    monkeypatch.setattr(engine, "_check_easyocr", lambda: False)
    monkeypatch.setattr(engine, "_check_paddle", lambda: False)
    engine._init_backend("auto")
    assert engine.backend_name is None
    assert engine.is_available is False


def test_explicit_backend_selection(monkeypatch):
    engine = OcrEngine.__new__(OcrEngine)
    engine.languages = ["rus"]
    engine.use_gpu = False
    monkeypatch.setattr(engine, "_check_easyocr", lambda: True)
    engine._init_backend("easyocr")
    assert engine.backend_name == "easyocr"


def test_explicit_backend_unavailable(monkeypatch):
    engine = OcrEngine.__new__(OcrEngine)
    engine.languages = ["rus"]
    engine.use_gpu = False
    monkeypatch.setattr(engine, "_check_paddle", lambda: False)
    engine._init_backend("paddle")
    assert engine.backend_name is None


def test_unknown_backend_falls_back_to_none(monkeypatch):
    engine = OcrEngine.__new__(OcrEngine)
    engine.languages = ["rus"]
    engine.use_gpu = False
    engine._init_backend("unknown")
    assert engine.backend_name is None
    assert engine.is_available is False


# --------------------------------------------------------------------------- #
# recognize(): поведение без бэкенда и с каждым бэкендом
# --------------------------------------------------------------------------- #
def test_recognize_unavailable_returns_empty(tmp_path):
    path = _make_image(tmp_path)
    engine = OcrEngine()
    engine._available = False
    result = engine.recognize(path)
    assert result.text == ""
    assert result.pages == 0


def test_recognize_handwriting_warns_and_proceeds(tmp_path, monkeypatch, caplog):
    path = _make_image(tmp_path)
    _install_pytesseract(monkeypatch)
    engine = _make_available_engine("tesseract")
    with caplog.at_level("WARNING", logger="textalchemy.recognize.ocr"):
        result = engine.recognize(path, handwriting=True)
    assert "does not natively support handwriting" in caplog.text
    assert result.text == "Привет мир"


def test_recognize_tesseract(tmp_path, monkeypatch):
    path = _make_image(tmp_path)
    _install_pytesseract(monkeypatch)
    engine = _make_available_engine("tesseract")
    result = engine.recognize(path)
    assert result.text == "Привет мир"
    assert result.language == "rus+eng"
    assert result.pages == 1
    assert result.confidence == pytest.approx(0.915)


def test_recognize_easyocr(tmp_path, monkeypatch):
    path = _make_image(tmp_path)
    _install_easyocr(monkeypatch)
    engine = _make_available_engine("easyocr")
    result = engine.recognize(path)
    assert result.text == "Hello"
    assert result.confidence == pytest.approx(0.9)


def test_recognize_easyocr_handwriting(tmp_path, monkeypatch):
    path = _make_image(tmp_path)
    _install_easyocr(monkeypatch)
    engine = _make_available_engine("easyocr")
    result = engine.recognize(path, handwriting=True)
    assert result.text == "Hello"


def test_recognize_paddle(tmp_path, monkeypatch):
    path = _make_image(tmp_path)
    _install_paddle(monkeypatch)
    engine = _make_available_engine("paddle")
    result = engine.recognize(path)
    assert result.text == "привет\nмир"


def test_recognize_backend_error_wrapped(tmp_path, monkeypatch):
    path = _make_image(tmp_path)
    _install_easyocr(monkeypatch)

    def boom(image, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(sys.modules["easyocr"].Reader, "readtext", boom)
    engine = _make_available_engine("easyocr")
    with pytest.raises(RecognizeError, match="OCR failed"):
        engine.recognize(path)


# --------------------------------------------------------------------------- #
# recognize_with_geometry(): геометрия по бэкендам
# --------------------------------------------------------------------------- #
def test_geometry_unavailable_returns_warning(tmp_path):
    path = _make_image(tmp_path)
    engine = OcrEngine()
    engine._available = False
    result = engine.recognize_with_geometry(path)
    assert result.warnings == ["no OCR backend available"]
    assert result.blocks == []


def test_geometry_missing_file():
    engine = OcrEngine()
    with pytest.raises(RecognizeError):
        engine.recognize_with_geometry("nonexistent.png")


def test_geometry_tesseract(tmp_path, monkeypatch):
    path = _make_image(tmp_path)
    _install_pytesseract(monkeypatch)
    engine = _make_available_engine("tesseract")
    result = engine.recognize_with_geometry(path, scale=3)
    assert len(result.blocks) == 2
    assert result.blocks[0].text == "Привет"
    assert result.blocks[0].bbox[0] == pytest.approx(10 / 3)
    assert result.blocks[0].confidence == pytest.approx(0.95)


def test_geometry_easyocr(tmp_path, monkeypatch):
    path = _make_image(tmp_path)
    _install_easyocr(monkeypatch)
    engine = _make_available_engine("easyocr")
    result = engine.recognize_with_geometry(path, scale=3)
    assert len(result.blocks) == 1
    assert result.blocks[0].text == "Hello"
    assert result.blocks[0].bbox == pytest.approx((10 / 3, 20 / 3, 20.0, 50 / 3))
    assert result.blocks[0].confidence == pytest.approx(0.9)


def test_geometry_easyocr_skips_empty(tmp_path, monkeypatch):
    path = _make_image(tmp_path)
    _install_easyocr(monkeypatch, results=[([[0, 0], [1, 0], [1, 1], [0, 1]], "   ", 0.9)])
    engine = _make_available_engine("easyocr")
    result = engine.recognize_with_geometry(path, scale=3)
    assert result.blocks == []


def test_geometry_paddle(tmp_path, monkeypatch):
    path = _make_image(tmp_path)
    _install_paddle(monkeypatch)
    engine = _make_available_engine("paddle")
    result = engine.recognize_with_geometry(path, scale=3)
    assert len(result.blocks) == 2
    assert result.blocks[0].text == "привет"
    assert result.blocks[0].bbox[2] == pytest.approx(20.0)
    assert result.blocks[1].bbox == (0.0, 0.0, 0.0, 0.0)  # нет box → нулевой bbox


def test_geometry_backend_error_wrapped(tmp_path, monkeypatch):
    path = _make_image(tmp_path)
    _install_pytesseract(monkeypatch)
    engine = _make_available_engine("tesseract")

    def boom(img, lang=None, output_type=None):
        raise RuntimeError("ts failed")

    monkeypatch.setattr(sys.modules["pytesseract"], "image_to_data", boom)
    with pytest.raises(RecognizeError, match="OCR geometry failed"):
        engine.recognize_with_geometry(path, scale=3)


# --------------------------------------------------------------------------- #
# recognize_pdf() / recognize_pdf_geometry(): постраничный разбор
# --------------------------------------------------------------------------- #
@pytest.fixture
def tiny_pdf(tmp_path):
    import fitz

    doc = fitz.open()
    doc.new_page(width=200, height=200)
    pdf_path = tmp_path / "tiny.pdf"
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def test_recognize_pdf_requires_pymupdf(monkeypatch, tmp_path):
    pdf_path = tmp_path / "x.pdf"
    pdf_path.write_bytes(b"dummy")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "fitz":
            raise ImportError("No module named 'fitz'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    engine = OcrEngine()
    with pytest.raises(RecognizeError, match="pymupdf"):
        engine.recognize_pdf(pdf_path)


def test_recognize_pdf_renders_pages(monkeypatch, tiny_pdf):
    engine = OcrEngine()
    engine._available = True
    monkeypatch.setattr(
        engine,
        "recognize",
        lambda image_path, handwriting=False: type(
            "R", (), {"text": "hi", "confidence": 0.9, "language": "rus", "pages": 1}
        )(),
    )
    results = engine.recognize_pdf(tiny_pdf, scale=2)
    assert len(results) == 1
    assert results[0].text == "hi"
    assert results[0].pages == 1


def test_recognize_pdf_clamps_scale(monkeypatch, tiny_pdf):
    engine = OcrEngine()
    engine._available = True
    monkeypatch.setattr(
        engine,
        "recognize",
        lambda image_path, handwriting=False: type(
            "R", (), {"text": "x", "confidence": 0.0, "language": "rus", "pages": 1}
        )(),
    )
    assert len(engine.recognize_pdf(tiny_pdf, scale=99)) == 1
    assert len(engine.recognize_pdf(tiny_pdf, scale=1)) == 1


def test_recognize_pdf_geometry_pages(monkeypatch, tiny_pdf):
    engine = OcrEngine()
    engine._available = True

    def fake_geometry(image_path, scale=3, handwriting=False):
        result = OcrPageResult(
            blocks=[OcrBlockGeometry(text="b", bbox=(0.0, 0.0, 1.0, 1.0), confidence=0.7)],
            language="rus",
        )
        return result

    monkeypatch.setattr(engine, "recognize_with_geometry", fake_geometry)
    results = engine.recognize_pdf_geometry(tiny_pdf, scale=2)
    assert len(results) == 1
    assert results[0].blocks[0].text == "b"
    assert results[0].blocks[0].page == 1
    assert results[0].pages == 1


def test_recognize_pdf_geometry_requires_pymupdf(monkeypatch, tmp_path):
    pdf_path = tmp_path / "x.pdf"
    pdf_path.write_bytes(b"dummy")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "fitz":
            raise ImportError("No module named 'fitz'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    engine = OcrEngine()
    with pytest.raises(RecognizeError, match="pymupdf"):
        engine.recognize_pdf_geometry(pdf_path)


# --------------------------------------------------------------------------- #
# _merge_word_blocks(): склейка слов в строки
# --------------------------------------------------------------------------- #
def _word(text, x0, x1, y0=0.0, y1=10.0, conf=0.5):
    return OcrBlockGeometry(text=text, bbox=(x0, y0, x1, y1), confidence=conf)


def test_merge_word_blocks_empty():
    assert _merge_word_blocks([]) == []


def test_merge_word_blocks_single():
    words = [_word("один", 0.0, 10.0)]
    merged = _merge_word_blocks(words)
    assert len(merged) == 1
    assert merged[0].text == "один"


def test_merge_word_blocks_merges_adjacent():
    words = [
        _word("привет", 0.0, 20.0),
        _word("мир", 21.0, 40.0),
    ]
    merged = _merge_word_blocks(words)
    assert len(merged) == 1
    assert merged[0].text == "привет мир"
    assert merged[0].bbox == (0.0, 0.0, 40.0, 10.0)
    assert merged[0].confidence == pytest.approx(0.5)


def test_merge_word_blocks_keeps_distant_words():
    words = [
        _word("левый", 0.0, 20.0),
        _word("правый", 200.0, 240.0),
    ]
    merged = _merge_word_blocks(words)
    assert len(merged) == 2
    assert merged[0].text == "левый"
    assert merged[1].text == "правый"


def test_merge_word_blocks_different_lines():
    words = [
        _word("верх", 0.0, 10.0, y0=0.0, y1=10.0),
        _word("низ", 0.0, 10.0, y0=100.0, y1=110.0),
    ]
    merged = _merge_word_blocks(words)
    assert len(merged) == 2


def test_merge_word_blocks_sorts_by_y_then_x():
    words = [
        _word("позже", 0.0, 10.0, y0=50.0, y1=60.0),
        _word("раньше", 0.0, 10.0, y0=0.0, y1=10.0),
    ]
    merged = _merge_word_blocks(words)
    assert [m.text for m in merged] == ["раньше", "позже"]
