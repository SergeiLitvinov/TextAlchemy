from __future__ import annotations

import io
import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PIL import Image

from textalchemy.core.exceptions import RecognizeError

logger = logging.getLogger(__name__)


@dataclass
class OcrResult:
    text: str
    confidence: float = 0.0
    language: str = "rus"
    pages: int = 0


DEFAULT_TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
DEFAULT_OCR_TIMEOUT = 30
DEFAULT_MIN_TEXT_LENGTH = 50
DEFAULT_DPI = 150
DEFAULT_LANGS = "rus+eng"


def preprocess_image(image: Image) -> Image:
    """Улучшенная предобработка изображения для OCR: grayscale → medianBlur → adaptiveThreshold → morphology."""
    try:
        import cv2
        import numpy as np
    except ImportError as e:
        raise RecognizeError("opencv-python required for image preprocessing") from e

    img_array = np.array(image)

    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array

    denoised = cv2.medianBlur(gray, 3)

    binary = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)

    kernel = np.ones((2, 2), np.uint8)
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

    return Image.fromarray(cleaned)


def render_page_to_image(page, dpi: int = DEFAULT_DPI, rotation: int = 0) -> Image:
    """Рендеринг страницы PDF в PIL Image с заданным DPI и поворотом."""
    import fitz

    scale = dpi / 72
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat)
    img_data = pix.tobytes("png")
    image = Image.open(io.BytesIO(img_data))
    if rotation:
        image = image.rotate(rotation, expand=True)
    return image


def _ocr_page_subprocess(
    image_path: Path,
    langs: str = DEFAULT_LANGS,
    psm: int = 6,
    timeout_sec: int = DEFAULT_OCR_TIMEOUT,
    tesseract_path: Optional[str] = None,
) -> tuple[str, bool]:
    """Запуск Tesseract через subprocess с таймаутом."""
    import pytesseract

    tesseract_cmd = tesseract_path or pytesseract.pytesseract.tesseract_cmd
    temp_output = tempfile.mktemp()

    cmd = [
        tesseract_cmd,
        str(image_path),
        temp_output,
        "-l",
        langs,
        "--psm",
        str(psm),
    ]

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        output_file = temp_output + ".txt"
        txt_path = Path(output_file)
        if txt_path.exists():
            text = txt_path.read_text(encoding="utf-8", errors="ignore")
            txt_path.unlink(missing_ok=True)
        else:
            text = ""
        Path(temp_output).unlink(missing_ok=True)
        return text, True
    except subprocess.TimeoutExpired:
        logger.warning("OCR timeout after %ss", timeout_sec)
        return "", False
    except Exception as e:
        logger.error("OCR error: %s", e)
        return "", False


class OcrEngine:
    def __init__(self, languages: Optional[List[str]] = None):
        self.languages = languages or ["rus", "eng"]
        self._backend: Optional[str] = None
        self._available = False
        self._detect_backend()

    def _detect_backend(self):
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            self._backend = "tesseract"
            self._available = True
            return
        except (ImportError, Exception):
            pass

        try:
            import easyocr  # noqa: F401

            self._backend = "easyocr"
            self._available = True
            return
        except ImportError:
            pass

        self._backend = None
        self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def backend_name(self) -> Optional[str]:
        return self._backend

    def recognize(
        self, image_path: str | Path, *, preprocess: bool = True, timeout: int = DEFAULT_OCR_TIMEOUT, psm: int = 6
    ) -> OcrResult:
        image_path = Path(image_path)
        if not image_path.exists():
            raise RecognizeError(f"Image not found: {image_path}")

        if not self._available:
            return OcrResult(
                text="",
                confidence=0.0,
                language=",".join(self.languages),
                pages=0,
            )

        try:
            if self._backend == "tesseract":
                return self._recognize_tesseract(image_path, preprocess=preprocess, timeout=timeout, psm=psm)
            elif self._backend == "easyocr":
                return self._recognize_easyocr(image_path, preprocess=preprocess)
        except Exception as e:
            raise RecognizeError(f"OCR failed: {e}") from e

        return OcrResult(text="")

    def _recognize_tesseract(
        self, image_path: Path, *, preprocess: bool = True, timeout: int = DEFAULT_OCR_TIMEOUT, psm: int = 6
    ) -> OcrResult:
        import pytesseract

        img = Image.open(image_path)
        if preprocess:
            img = preprocess_image(img)

        lang = "+".join(self.languages)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
            img.save(tmp_path)

        try:
            text, ok = _ocr_page_subprocess(
                Path(tmp_path),
                langs=lang,
                psm=psm,
                timeout_sec=timeout,
            )
            if not ok:
                text = ""
            data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
            confidences = [int(c) for c in data["conf"] if c != "-1"]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        return OcrResult(
            text=text.strip(),
            confidence=avg_conf / 100.0,
            language=lang,
            pages=1,
        )

    def _recognize_easyocr(self, image_path: Path, *, preprocess: bool = True) -> OcrResult:
        import easyocr

        img = Image.open(image_path)
        if preprocess:
            img = preprocess_image(img)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
            img.save(tmp_path)

        try:
            reader = easyocr.Reader(self.languages, gpu=False)
            results = reader.readtext(str(tmp_path))
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        text_parts: list[str] = []
        confs: list[float] = []
        for bbox, text, conf in results:
            text_parts.append(text)
            confs.append(conf)

        return OcrResult(
            text="\n".join(text_parts),
            confidence=sum(confs) / len(confs) if confs else 0.0,
            language=",".join(self.languages),
            pages=1,
        )

    def recognize_pdf(
        self,
        pdf_path: str | Path,
        dpi: int = DEFAULT_DPI,
        langs: Optional[str] = None,
        timeout: int = DEFAULT_OCR_TIMEOUT,
        psm: int = 6,
        min_text_length: int = DEFAULT_MIN_TEXT_LENGTH,
        rotation: int = 0,
        use_ocr: bool = True,
    ) -> list[OcrResult]:
        """Двухуровневое извлечение текста из PDF: текстовый слой → OCR.

        Если на странице достаточно текста из текстового слоя (>min_text_length),
        OCR не запускается. Иначе — рендеринг + предобработка + Tesseract.
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise RecognizeError(f"PDF not found: {pdf_path}")

        try:
            import fitz
        except ImportError as e:
            raise RecognizeError("pymupdf (fitz) required for PDF OCR") from e

        doc = fitz.open(str(pdf_path))
        results: list[OcrResult] = []
        lang_str = langs or "+".join(self.languages)

        for page_num in range(len(doc)):
            page = doc[page_num]
            text_layer = page.get_text()

            if len(text_layer.strip()) > min_text_length:
                results.append(
                    OcrResult(
                        text=text_layer.strip(),
                        confidence=1.0,
                        language=lang_str,
                        pages=len(doc),
                    )
                )
                continue

            if not use_ocr:
                results.append(OcrResult(text="", language=lang_str, pages=len(doc)))
                continue

            img = render_page_to_image(page, dpi=dpi, rotation=rotation)
            img = preprocess_image(img)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                tmp_path = f.name
                img.save(tmp_path)

            try:
                text, ok = _ocr_page_subprocess(
                    Path(tmp_path),
                    langs=lang_str,
                    psm=psm,
                    timeout_sec=timeout,
                )
                if not ok:
                    text = ""
                results.append(
                    OcrResult(
                        text=text.strip(),
                        confidence=0.0 if not text else 0.5,
                        language=lang_str,
                        pages=len(doc),
                    )
                )
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        return results

    def recognize_page_with_ocr(
        self,
        page,
        langs: str = DEFAULT_LANGS,
        dpi: int = DEFAULT_DPI,
        rotation: int = 0,
        psm: int = 6,
        timeout_sec: int = DEFAULT_OCR_TIMEOUT,
    ) -> tuple[str, bool]:
        """Обработка одной страницы PDF через OCR с предобработкой."""

        img = render_page_to_image(page, dpi=dpi, rotation=rotation)
        img = preprocess_image(img)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
            img.save(tmp_path)

        try:
            return _ocr_page_subprocess(
                Path(tmp_path),
                langs=langs,
                psm=psm,
                timeout_sec=timeout_sec,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)


__all__ = [
    "OcrEngine",
    "OcrResult",
    "preprocess_image",
    "render_page_to_image",
    "DEFAULT_TESSERACT_PATH",
    "DEFAULT_OCR_TIMEOUT",
    "DEFAULT_MIN_TEXT_LENGTH",
    "DEFAULT_DPI",
    "DEFAULT_LANGS",
]
