from __future__ import annotations

from pathlib import Path

import pytest

from textalchemy.recognize import OcrEngine


def test_ocr_engine_init():
    engine = OcrEngine(languages=["rus", "eng"])
    assert engine.languages == ["rus", "eng"]


def test_ocr_recognize_no_file():
    engine = OcrEngine()
    with pytest.raises(Exception):
        engine.recognize("nonexistent.png")


def test_ocr_backend_auto():
    engine = OcrEngine()
    assert engine.backend_name in (None, "tesseract", "easyocr")


class TestPreprocessImage:
    def test_with_opencv(self):
        """preprocess_image создаёт новое PIL.Image при наличии opencv."""
        pytest.importorskip("cv2")
        import numpy as np
        from PIL import Image

        from textalchemy.recognize.ocr import preprocess_image

        img = Image.fromarray(np.ones((100, 100, 3), dtype=np.uint8) * 255)
        result = preprocess_image(img)
        assert isinstance(result, Image.Image)

    def test_grayscale_input(self):
        pytest.importorskip("cv2")
        import numpy as np
        from PIL import Image

        from textalchemy.recognize.ocr import preprocess_image

        gray = Image.fromarray(np.ones((50, 50), dtype=np.uint8) * 128)
        result = preprocess_image(gray)
        assert isinstance(result, Image.Image)


class TestRenderPageToImage:
    def test_basic_render(self, monkeypatch):
        """render_page_to_image возвращает PIL.Image."""
        import io

        import numpy as np
        from PIL import Image

        from textalchemy.recognize.ocr import render_page_to_image

        img_bytes = io.BytesIO()
        Image.fromarray(np.ones((10, 10, 3), dtype=np.uint8) * 255).save(img_bytes, format="PNG")
        png_data = img_bytes.getvalue()

        class MockPixmap:
            def tobytes(self, fmt):
                return png_data

        class MockPage:
            def get_pixmap(self, matrix=None):
                return MockPixmap()

        result = render_page_to_image(MockPage(), dpi=72)
        assert isinstance(result, Image.Image)

    def test_with_rotation(self, monkeypatch):
        import numpy as np
        from PIL import Image

        from textalchemy.recognize.ocr import render_page_to_image

        class MockPixmap:
            def tobytes(self, fmt):
                import io

                buf = io.BytesIO()
                Image.fromarray(np.ones((10, 10, 3), dtype=np.uint8) * 255).save(buf, format="PNG")
                return buf.getvalue()

        class MockPage:
            def get_pixmap(self, matrix=None):
                return MockPixmap()

        result = render_page_to_image(MockPage(), dpi=72, rotation=90)
        assert isinstance(result, Image.Image)
        assert result.size == (10, 10)


class TestOcrPageSubprocess:
    @staticmethod
    def _mock_pytesseract(monkeypatch):
        import sys

        class FakePytesseract:
            class pytesseract:  # noqa: N801
                tesseract_cmd = "tesseract"

        monkeypatch.setitem(sys.modules, "pytesseract", FakePytesseract)

    def test_timeout_returns_false(self, monkeypatch):
        import subprocess

        self._mock_pytesseract(monkeypatch)
        from textalchemy.recognize.ocr import _ocr_page_subprocess

        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="tesseract", timeout=1)

        monkeypatch.setattr(subprocess, "run", fake_run)
        text, ok = _ocr_page_subprocess(Path("dummy.png"), timeout_sec=1)
        assert text == ""
        assert ok is False

    def test_success_returns_text(self, tmp_path, monkeypatch):
        import subprocess

        self._mock_pytesseract(monkeypatch)
        from textalchemy.recognize.ocr import _ocr_page_subprocess

        real_mktemp = __import__("tempfile").mktemp
        created = []

        def tracking_mktemp():
            p = real_mktemp()
            created.append(p)
            return p

        monkeypatch.setattr("tempfile.mktemp", tracking_mktemp)

        def fake_run(*args, **kwargs):
            if created:
                Path(created[-1] + ".txt").write_text("hello@example.com", encoding="utf-8")
            return subprocess.CompletedProcess(args[0], 0)

        monkeypatch.setattr(subprocess, "run", fake_run)
        text, ok = _ocr_page_subprocess(Path("dummy.png"))
        assert ok is True
        assert "hello@example.com" in text

    def test_error_returns_false(self, monkeypatch):
        import subprocess

        self._mock_pytesseract(monkeypatch)
        from textalchemy.recognize.ocr import _ocr_page_subprocess

        def fake_run(*args, **kwargs):
            raise RuntimeError("tesseract not found")

        monkeypatch.setattr(subprocess, "run", fake_run)
        text, ok = _ocr_page_subprocess(Path("dummy.png"))
        assert text == ""
        assert ok is False
