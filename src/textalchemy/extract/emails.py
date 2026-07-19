from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Sequence

from textalchemy.core.exceptions import RecognizeError
from textalchemy.core.types import DocFormat, Document

if TYPE_CHECKING:
    from textalchemy.recognize.ocr import OcrEngine

logger = logging.getLogger(__name__)


INVALID_TLDS = frozenset({".abc", ".test", ".invalid", ".localhost", ".example"})
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


@dataclass
class EmailResult:
    emails: list[str] = field(default_factory=list)
    source: str = ""
    total_pages: int = 0
    text_pages: int = 0
    ocr_pages: int = 0


def extract_emails_from_text(text: str) -> list[str]:
    """Поиск email с помощью регулярного выражения с валидацией."""
    emails = EMAIL_PATTERN.findall(text)

    valid: list[str] = []
    for email in emails:
        domain = email.split("@")[1].lower()
        tld = "." + domain.split(".")[-1]
        if tld not in INVALID_TLDS and len(tld) <= 6:
            valid.append(email)

    return list(set(valid))


def extract_emails_from_pdf(
    pdf_path: str | Path,
    *,
    dpi: int = 150,
    langs: str = "rus+eng",
    timeout: int = 30,
    psm: int = 6,
    min_text_length: int = 50,
    rotation: int = 0,
    use_ocr: bool = True,
    ocr_engine: Optional["OcrEngine"] = None,
) -> EmailResult:
    """Двухуровневое извлечение email из PDF: текстовый слой → OCR.

    Без OCR использует ``formats/pdf.read_pdf()`` (pdfplumber → pypdf → pymupdf).
    C OCR — построчный обход через fitz + Tesseract для страниц без текстового слоя.
    """
    from textalchemy.formats.pdf import read_pdf

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise RecognizeError(f"PDF not found: {pdf_path}")

    if not use_ocr:
        result = read_pdf(str(pdf_path))
        emails = extract_emails_from_text(result.plain)
        return EmailResult(
            emails=sorted(set(emails)),
            source=str(pdf_path),
            total_pages=result.pages,
            text_pages=result.pages,
            ocr_pages=0,
        )

    from textalchemy.recognize.ocr import OcrEngine

    try:
        import fitz
    except ImportError as e:
        raise RecognizeError("pymupdf (fitz) required for PDF OCR") from e

    engine = ocr_engine or OcrEngine(languages=langs.split("+"))
    all_emails: list[str] = []
    text_pages = 0
    ocr_pages = 0

    with fitz.open(str(pdf_path)) as doc:
        for i, page in enumerate(doc, 1):
            text_layer = page.get_text()

            if len(text_layer.strip()) > min_text_length:
                text_pages += 1
                page_emails = extract_emails_from_text(text_layer)
                all_emails.extend(page_emails)
                continue

            ocr_pages += 1
            text, ok = engine.recognize_page_with_ocr(
                page,
                langs=langs,
                dpi=dpi,
                rotation=rotation,
                psm=psm,
                timeout_sec=timeout,
            )
            if ok and text:
                page_emails = extract_emails_from_text(text)
                all_emails.extend(page_emails)

    return EmailResult(
        emails=sorted(set(all_emails)),
        source=str(pdf_path),
        total_pages=len(doc),
        text_pages=text_pages,
        ocr_pages=ocr_pages,
    )


def extract_emails_from_document(
    document: Document,
    *,
    langs: str = "rus+eng",
    dpi: int = 150,
    timeout: int = 30,
    psm: int = 6,
    min_text_length: int = 50,
    rotation: int = 0,
    use_ocr: bool = True,
) -> EmailResult:
    """Извлечение email из Document (PDF/DOCX/TXT)."""
    path = document.path

    if document.format == DocFormat.PDF:
        return extract_emails_from_pdf(
            path,
            dpi=dpi,
            langs=langs,
            timeout=timeout,
            psm=psm,
            min_text_length=min_text_length,
            rotation=rotation,
            use_ocr=use_ocr,
        )

    text = path.read_text(encoding="utf-8", errors="ignore")
    emails = extract_emails_from_text(text)

    return EmailResult(
        emails=sorted(emails),
        source=str(path),
        total_pages=1,
        text_pages=1,
        ocr_pages=0,
    )


def emails_to_docx(emails: Sequence[str], source_name: str, output_path: str | Path) -> Path:
    """Сохранение списка email в Word документ."""
    from docx import Document as DocxDocument

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = DocxDocument()
    doc.add_heading(f"Email из файла: {Path(source_name).name}", 0)
    doc.add_paragraph(f"Всего найдено уникальных адресов: {len(emails)}")
    doc.add_paragraph(f"Дата обработки: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    doc.add_heading("Список адресов:", level=1)

    if not emails:
        doc.add_paragraph("❌ Email адреса не найдены.")
    else:
        for email in sorted(emails):
            doc.add_paragraph(email)

    doc.save(str(out))
    logger.info("DOCX saved: %s", out)
    return out


def emails_to_text(emails: Sequence[str], source_name: str, output_path: str | Path) -> Path:
    """Сохранение списка email в текстовый файл (по одному email на строку)."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    content = "\n".join(sorted(emails)) if emails else "Email адреса не найдены."
    out.write_text(content, encoding="utf-8")
    logger.info("TXT saved: %s", out)
    return out


def save_debug_text(
    full_text: str, pdf_name: str, total_pages: int, text_pages: int, ocr_pages: int, output_path: str | Path
) -> Path:
    """Сохранение отладочного файла с распознанным текстом."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "=== РАСПОЗНАННЫЙ ТЕКСТ ===",
        f"Файл: {pdf_name}",
        f"Страниц всего: {total_pages}",
        f"Страниц с текстовым слоем: {text_pages}",
        f"Страниц с OCR: {ocr_pages}",
        "=" * 50 + "\n",
        full_text,
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Debug text saved: %s", out)
    return out


__all__ = [
    "EmailResult",
    "extract_emails_from_text",
    "extract_emails_from_pdf",
    "extract_emails_from_document",
    "emails_to_docx",
    "emails_to_text",
    "save_debug_text",
]
