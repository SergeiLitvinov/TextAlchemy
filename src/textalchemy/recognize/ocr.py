from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from textalchemy.core.exceptions import RecognizeError


@dataclass
class OcrResult:
    text: str
    confidence: float = 0.0
    language: str = "rus"
    pages: int = 0


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

    def recognize(self, image_path: str | Path) -> OcrResult:
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
                return self._recognize_tesseract(image_path)
            elif self._backend == "easyocr":
                return self._recognize_easyocr(image_path)
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

    def _recognize_easyocr(self, image_path: Path) -> OcrResult:
        import easyocr

        reader = easyocr.Reader(self.languages, gpu=False)
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

    def recognize_pdf(self, pdf_path: str | Path, dpi: int = 300) -> List[OcrResult]:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise RecognizeError(f"PDF not found: {pdf_path}")

        try:
            import fitz
            from PIL import Image
        except ImportError:
            raise RecognizeError("pymupdf (fitz) required for PDF OCR")

        import tempfile

        doc = fitz.open(str(pdf_path))
        results: list[OcrResult] = []

        with tempfile.TemporaryDirectory(prefix="textalchemy_ocr_") as tmpdir:
            tmp = Path(tmpdir)
            for page_num in range(len(doc)):
                page = doc[page_num]
                pix = page.get_pixmap(dpi=dpi)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                temp_img = tmp / f"page_{page_num}.png"
                img.save(temp_img)
                result = self.recognize(temp_img)
                result.pages = len(doc)
                results.append(result)

        return results
