"""OCR subsystem — Tesseract / EasyOCR / PaddleOCR backends.

Also provides ``recognize_with_geometry()`` which returns per-block results
with bounding boxes — used for merging text layer and OCR (see
``textalchemy.formats.pdf_ocr_merge``).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from textalchemy.core.exceptions import RecognizeError
from textalchemy.formats.pdf_ocr_types import OcrBlockGeometry, OcrPageResult

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

    def __init__(self, languages: Optional[List[str]] = None, use_gpu: bool = False, backend: str = "auto"):
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
                "Backend %r does not natively support handwriting mode; proceeding in printed-text mode.",
                self._backend,
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

    def recognize_with_geometry(self, image_path: str | Path, scale: int = 3, handwriting: bool = False) -> OcrPageResult:
        """Recognise text and return per-block results with bounding boxes.

        Uses the scale factor to transform image-space bboxes back to PDF
        page-space coordinates. Default scale=3 matches ``recognize_pdf``.
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise RecognizeError(f"Image not found: {image_path}")

        if not self._available:
            return OcrPageResult(
                language=",".join(self.languages),
                warnings=["no OCR backend available"],
            )

        try:
            if self._backend == "tesseract":
                return self._recognize_tesseract_geometry(image_path, scale)
            elif self._backend == "easyocr":
                return self._recognize_easyocr_geometry(image_path, scale, handwriting)
            elif self._backend == "paddle":
                return self._recognize_paddle_geometry(image_path, scale)
        except Exception as e:
            raise RecognizeError(f"OCR geometry failed: {e}") from e

        return OcrPageResult(warnings=["unable to run OCR"])

    def _recognize_tesseract_geometry(self, image_path: Path, scale: int) -> OcrPageResult:
        import pytesseract
        from PIL import Image

        img = Image.open(image_path)
        lang = "+".join(self.languages)
        data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)

        blocks: list[OcrBlockGeometry] = []
        img_w, img_h = img.size
        n = len(data.get("text", []))
        for i in range(n):
            text = (data.get("text") or [""])[i]
            conf_str = (data.get("conf") or ["-1"])[i]
            left = int((data.get("left") or [0])[i])
            top = int((data.get("top") or [0])[i])
            w = int((data.get("width") or [0])[i])
            h = int((data.get("height") or [0])[i])
            level = int((data.get("level") or [1])[i])

            if not text or not text.strip():
                continue
            if level != 5:  # only word-level
                continue

            conf = int(conf_str) / 100.0 if conf_str != "-1" else 0.0
            x0 = left / scale
            y0 = top / scale
            x1 = (left + w) / scale
            y1 = (top + h) / scale
            blocks.append(
                OcrBlockGeometry(
                    text=text.strip(),
                    bbox=(x0, y0, x1, y1),
                    confidence=max(0.0, conf),
                )
            )

        # Merge adjacent words into line-level blocks
        merged = _merge_word_blocks(blocks)
        return OcrPageResult(blocks=merged, language=lang)

    def _recognize_easyocr_geometry(self, image_path: Path, scale: int, handwriting: bool = False) -> OcrPageResult:
        import easyocr
        from PIL import Image

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

        img_w, img_h = Image.open(image_path).size
        blocks: list[OcrBlockGeometry] = []
        for bbox, text, confidence in results:
            if not text.strip():
                continue
            # bbox from easyocr is [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
            xs = [pt[0] for pt in bbox]
            ys = [pt[1] for pt in bbox]
            x0 = min(xs) / scale
            y0 = min(ys) / scale
            x1 = max(xs) / scale
            y1 = max(ys) / scale
            blocks.append(
                OcrBlockGeometry(
                    text=text.strip(),
                    bbox=(x0, y0, x1, y1),
                    confidence=float(confidence),
                )
            )

        return OcrPageResult(blocks=blocks, language=",".join(self.languages))

    def _recognize_paddle_geometry(self, image_path: Path, scale: int) -> OcrPageResult:
        from paddleocr import PaddleOCR
        from PIL import Image

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

        img_w, img_h = Image.open(image_path).size
        blocks: list[OcrBlockGeometry] = []
        if result and result[0]:
            for item in result[0]:
                if not item or "text" not in item:
                    continue
                text = item["text"]
                if not text.strip():
                    continue
                confidence = float(item.get("confidence", 0.0))
                # box is [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                box = item.get("box", [])
                if box and len(box) == 4:
                    xs = [pt[0] for pt in box]
                    ys = [pt[1] for pt in box]
                    x0 = min(xs) / scale
                    y0 = min(ys) / scale
                    x1 = max(xs) / scale
                    y1 = max(ys) / scale
                else:
                    x0 = y0 = x1 = y1 = 0.0
                blocks.append(
                    OcrBlockGeometry(
                        text=text.strip(),
                        bbox=(x0, y0, x1, y1),
                        confidence=confidence,
                    )
                )

        return OcrPageResult(blocks=blocks, language=lang)

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

    def recognize_pdf(
        self, pdf_path: str | Path, scale: int = 3, handwriting: bool = False, save_images: bool = False
    ) -> List[OcrResult]:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise RecognizeError(f"PDF not found: {pdf_path}")

        try:
            import fitz
        except ImportError:
            raise RecognizeError("pymupdf (fitz) required for PDF OCR")

        from textalchemy.core.artifacts import ArtifactWorkspace

        scale = max(2, min(6, scale))

        results: list[OcrResult] = []

        with fitz.open(str(pdf_path)) as doc:
            with ArtifactWorkspace(prefix="textalchemy_ocr_") as ws:
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    mat = fitz.Matrix(scale, scale)
                    pix = page.get_pixmap(matrix=mat)

                    from PIL import Image

                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                    if save_images:
                        import io

                        from textalchemy.core.io import atomic_write_bytes

                        save_path = Path.cwd() / f"page_{page_num + 1}.png"
                        buffer = io.BytesIO()
                        img.save(buffer, format="PNG")
                        atomic_write_bytes(save_path, buffer.getvalue())
                    else:
                        save_path = ws.artifact_path(f"page_{page_num}.png")
                        img.save(save_path)
                        ws.validate_artifact(save_path)
                    result = self.recognize(save_path, handwriting=handwriting)

                    result.pages = len(doc)
                    results.append(result)

        return results

    def recognize_pdf_geometry(self, pdf_path: str | Path, scale: int = 3, handwriting: bool = False) -> list[OcrPageResult]:
        """OCR PDF page-by-page, returning geometry blocks with bboxes.

        The scale factor (2-6) controls rendering resolution. Higher values
        improve accuracy at the cost of speed.
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise RecognizeError(f"PDF not found: {pdf_path}")

        try:
            import fitz
        except ImportError:
            raise RecognizeError("pymupdf (fitz) required for PDF OCR")

        from textalchemy.core.artifacts import ArtifactWorkspace

        scale = max(2, min(6, scale))
        results: list[OcrPageResult] = []

        with fitz.open(str(pdf_path)) as doc:
            with ArtifactWorkspace(prefix="textalchemy_ocr_") as ws:
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    mat = fitz.Matrix(scale, scale)
                    pix = page.get_pixmap(matrix=mat)

                    from PIL import Image

                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                    save_path = ws.artifact_path(f"page_{page_num}.png")
                    img.save(save_path)
                    ws.validate_artifact(save_path)
                    page_result = self.recognize_with_geometry(save_path, scale=scale, handwriting=handwriting)
                    page_result.pages = len(doc)
                    for block in page_result.blocks:
                        object.__setattr__(block, "page", page_num + 1)
                    results.append(page_result)

        return results


def _merge_word_blocks(words: list[OcrBlockGeometry], merge_distance: float = 4.0) -> list[OcrBlockGeometry]:
    """Merge adjacent word-level OCR blocks into line-level blocks.

    Words on the same vertical band (y-axis overlap) and close horizontally
    are merged into a single block. This reduces noise in downstream merging
    with PDF text layer blocks.
    """
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: (w.bbox[1], w.bbox[0]))
    merged: list[OcrBlockGeometry] = []
    current = sorted_words[0]

    for word in sorted_words[1:]:
        # Same line: vertical overlap and horizontal proximity
        vert_overlap = min(current.bbox[3], word.bbox[3]) - max(current.bbox[1], word.bbox[1])
        if vert_overlap > -2.0 and (word.bbox[0] - current.bbox[2]) <= merge_distance:
            x0 = min(current.bbox[0], word.bbox[0])
            y0 = min(current.bbox[1], word.bbox[1])
            x1 = max(current.bbox[2], word.bbox[2])
            y1 = max(current.bbox[3], word.bbox[3])
            conf = (current.confidence + word.confidence) / 2.0
            current = OcrBlockGeometry(
                text=current.text + " " + word.text,
                bbox=(x0, y0, x1, y1),
                confidence=conf,
                page=current.page,
            )
        else:
            merged.append(current)
            current = word
    merged.append(current)
    return merged
