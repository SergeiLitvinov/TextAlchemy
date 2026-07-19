import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from textalchemy.core.exceptions import RecognizeError

logger = logging.getLogger(__name__)

# Бэкенды, которые реально поддерживают режим handwriting.
_HANDWRITING_BACKENDS = {"easyocr"}


@dataclass
class OcrResult:
    text: str
    confidence: float = 0.0
    language: str = "rus"
    pages: int = 0


class OcrEngine:
    _BACKENDS = ["tesseract", "easyocr", "paddle"]

    def __init__(self, languages: Optional[List[str]] = None, use_gpu: bool = False,
                 backend: str = "auto"):
        self.languages = languages or ["rus", "eng"]
        self.use_gpu = use_gpu
        self._backend: Optional[str] = None
        self._available = False
        self._init_backend(backend)

    def _check_tesseract(self) -> bool:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except (ImportError, OSError):
            return False

    def _check_easyocr(self) -> bool:
        try:
            import easyocr  # noqa: F401
            return True
        except ImportError:
            return False

    def _check_paddle(self) -> bool:
        try:
            import paddleocr  # noqa: F401
            return True
        except ImportError:
            return False

    def _init_backend(self, backend: str):
        if backend == "auto":
            for name in self._BACKENDS:
                check = getattr(self, f"_check_{name}")
                if check():
                    self._backend = name
                    self._available = True
                    return
        elif backend in self._BACKENDS:
            check = getattr(self, f"_check_{backend}")
            if check():
                self._backend = backend
                self._available = True
                return
        self._backend = None
        self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def backend_name(self) -> Optional[str]:
        return self._backend

    def recognize(self, image_path: str | Path, handwriting: bool = False) -> OcrResult:
        image_path = Path(image_path)
        if not image_path.exists():
            raise RecognizeError(f"Image not found: {image_path}")

        if handwriting and self._backend not in _HANDWRITING_BACKENDS:
            logger.warning(
                "Backend %r does not natively support handwriting mode; "
                "proceeding in printed-text mode.", self._backend,
            )

        if not self._available:
            return OcrResult(
                text="",
                confidence=0.0,
                language=",".join(self.languages),
                pages=0,
            )

        try:
            if self._backend == "tesseract":
                return self._recognize_tesseract(image_path)
            elif self._backend == "easyocr":
                return self._recognize_easyocr(image_path, handwriting)
            elif self._backend == "paddle":
                return self._recognize_paddle(image_path)
        except Exception as e:
            raise RecognizeError(f"OCR failed: {e}") from e

        return OcrResult(text="")

    def _recognize_tesseract(self, image_path: Path) -> OcrResult:
        import pytesseract
        from PIL import Image

        img = Image.open(image_path)
        lang = "+".join(self.languages)
        data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)

        text = pytesseract.image_to_string(img, lang=lang)
        confidences = [int(c) for c in data["conf"] if c != "-1"]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return OcrResult(
            text=text.strip(),
            confidence=avg_conf / 100.0,
            language=lang,
            pages=1,
        )

    def _recognize_easyocr(self, image_path: Path, handwriting: bool = False) -> OcrResult:
        import easyocr

        reader = easyocr.Reader(self.languages, gpu=self.use_gpu)

        if handwriting:
            results = reader.readtext(
                str(image_path),
                detail=1,
                paragraph=True,
                min_size=10,
                text_threshold=0.5,
                low_text=0.4,
                link_threshold=0.2,
                canvas_size=2560,
                mag_ratio=1.0,
            )
        else:
            results = reader.readtext(str(image_path))

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

    def _recognize_paddle(self, image_path: Path) -> OcrResult:
        from paddleocr import PaddleOCR

        lang = "ru" if "ru" in self.languages else "en"

        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

        ocr = PaddleOCR(
            lang=lang,
            text_det_thresh=0.3,
            text_det_box_thresh=0.5,
            text_recognition_batch_size=8,
            use_textline_orientation=True,
        )

        result = ocr.predict(str(image_path))

        lines: list[str] = []
        if result and result[0]:
            for item in result[0]:
                if item and "text" in item:
                    lines.append(item["text"])

        return OcrResult(
            text="\n".join(lines),
            confidence=0.0,
            language=",".join(self.languages),
            pages=1,
        )

    def recognize_pdf(self, pdf_path: str | Path, scale: int = 3,
                       handwriting: bool = False, save_images: bool = False) -> List[OcrResult]:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise RecognizeError(f"PDF not found: {pdf_path}")

        try:
            import fitz
        except ImportError:
            raise RecognizeError("pymupdf (fitz) required for PDF OCR")

        import tempfile

        doc = fitz.open(str(pdf_path))

        scale = max(2, min(6, scale))

        results: list[OcrResult] = []

        with tempfile.TemporaryDirectory(prefix="textalchemy_ocr_") as tmpdir:
            tmp = Path(tmpdir)
            for page_num in range(len(doc)):
                page = doc[page_num]
                mat = fitz.Matrix(scale, scale)
                pix = page.get_pixmap(matrix=mat)

                from PIL import Image
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                if save_images:
                    save_path = Path.cwd() / f"page_{page_num + 1}.png"
                else:
                    save_path = tmp / f"page_{page_num}.png"
                img.save(save_path)
                result = self.recognize(save_path, handwriting=handwriting)

                result.pages = len(doc)
                results.append(result)

        return results
