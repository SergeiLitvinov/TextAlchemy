import pytest

from textalchemy.recognize import OcrEngine


def test_ocr_engine_init():
    engine = OcrEngine(languages=["rus", "eng"])
    assert engine.languages == ["rus", "eng"]


def test_ocr_engine_init_with_gpu():
    engine = OcrEngine(languages=["rus", "eng"], use_gpu=True)
    assert engine.use_gpu is True


def test_ocr_recognize_no_file():
    engine = OcrEngine()
    with pytest.raises(Exception):
        engine.recognize("nonexistent.png")


def test_ocr_recognize_no_file_handwriting():
    engine = OcrEngine()
    with pytest.raises(Exception):
        engine.recognize("nonexistent.png", handwriting=True)


def test_ocr_backend_auto():
    engine = OcrEngine()
    assert engine.backend_name in (None, "tesseract", "easyocr", "paddle")


def test_ocr_recognize_pdf_no_file():
    engine = OcrEngine()
    with pytest.raises(Exception):
        engine.recognize_pdf("nonexistent.pdf")


def test_ocr_recognize_pdf_no_file_handwriting():
    engine = OcrEngine()
    with pytest.raises(Exception):
        engine.recognize_pdf("nonexistent.pdf", handwriting=True)
