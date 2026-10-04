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
    Для страниц без текста получает PNG через OpenDoc Formats и запускает OCR.
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

    from opendoc_formats.pdf import PdfDocument

    from textalchemy.recognize.ocr import OcrEngine

    engine = ocr_engine or OcrEngine(languages=langs.split("+"))
    all_emails: list[str] = []
    text_pages = 0
    ocr_pages = 0

    with PdfDocument(pdf_path) as doc:
        total_pages = doc.page_count
        for index in range(total_pages):
            text_layer = doc.page_info(index).text

            if len(text_layer.strip()) > min_text_length:
                text_pages += 1
                page_emails = extract_emails_from_text(text_layer)
                all_emails.extend(page_emails)
                continue

            ocr_pages += 1
            png = doc.render_page(index, dpi=dpi, rotation=rotation).png
            result = engine.recognize_image_bytes(png, langs=langs, psm=psm, timeout=timeout)
            if result.text:
                page_emails = extract_emails_from_text(result.text)
                all_emails.extend(page_emails)

    return EmailResult(
        emails=sorted(set(all_emails)),
        source=str(pdf_path),
        total_pages=total_pages,
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
    from opendoc import DocumentModel, Paragraph, Section, TextRun
    from opendoc_formats.writers.docx_writer import write_docx_model

    out = Path(output_path)
    blocks = [
        Paragraph([TextRun(f"Email из файла: {Path(source_name).name}")], properties={"style_name": "Title"}),
        Paragraph([TextRun(f"Всего найдено уникальных адресов: {len(emails)}")]),
        Paragraph([TextRun(f"Дата обработки: {datetime.now().strftime('%d.%m.%Y %H:%M')}")]),
        Paragraph([TextRun("Список адресов:")], properties={"style_name": "Heading 1"}),
        *(Paragraph([TextRun(email)]) for email in sorted(emails)),
    ]
    if not emails:
        blocks.append(Paragraph([TextRun("❌ Email адреса не найдены.")]))
    report = write_docx_model(DocumentModel(sections=[Section(blocks=blocks)]), out)
    if not report.success:
        raise RecognizeError("Не удалось сохранить список адресов в DOCX")
    logger.info("DOCX saved: %s", out)
    return out


def emails_to_text(emails: Sequence[str], source_name: str, output_path: str | Path) -> Path:
    """Сохранение списка email в текстовый файл (по одному email на строку)."""
    from textalchemy.core.io import atomic_write_text

    out = Path(output_path)

    content = "\n".join(sorted(emails)) if emails else "Email адреса не найдены."
    atomic_write_text(out, content, encoding="utf-8")
    logger.info("TXT saved: %s", out)
    return out


def save_debug_text(
    full_text: str, pdf_name: str, total_pages: int, text_pages: int, ocr_pages: int, output_path: str | Path
) -> Path:
    """Сохранение отладочного файла с распознанным текстом."""
    from textalchemy.core.io import atomic_write_text

    out = Path(output_path)

    lines = [
        "=== РАСПОЗНАННЫЙ ТЕКСТ ===",
        f"Файл: {pdf_name}",
        f"Страниц всего: {total_pages}",
        f"Страниц с текстовым слоем: {text_pages}",
        f"Страниц с OCR: {ocr_pages}",
        "=" * 50 + "\n",
        full_text,
    ]
    atomic_write_text(out, "\n".join(lines), encoding="utf-8")
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
