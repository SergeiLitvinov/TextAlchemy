from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence, Union

from textalchemy.core.registry import operation
from textalchemy.core.types import Document

logger = logging.getLogger(__name__)


@operation(
    "extract.emails",
    input_type="Document",
    output_type="list[str]",
    input_param="doc",
    description="Document → list[str] (email адреса). PDF: текстовый слой + OCR.",
    tags=["extract", "emails"],
)
def extract_emails(
    *,
    doc: Document,
    langs: str = "rus+eng",
    dpi: int = 150,
    timeout: int = 30,
    psm: int = 6,
    min_text_length: int = 50,
    rotation: int = 0,
    use_ocr: bool = True,
) -> list[str]:
    """Извлечение email из документа. Поддержка PDF (с OCR), DOCX, TXT.

    Все параметры keyword-only. Возвращает отсортированный список уникальных email.
    """
    from textalchemy.extract.emails import extract_emails_from_document

    result = extract_emails_from_document(
        doc,
        langs=langs,
        dpi=dpi,
        timeout=timeout,
        psm=psm,
        min_text_length=min_text_length,
        rotation=rotation,
        use_ocr=use_ocr,
    )
    return result.emails


@operation(
    "render.emails.docx",
    input_type="list[str]",
    output_type="Path",
    input_param="emails",
    description="list[str] → DOCX (email адреса в Word).",
    tags=["render", "emails"],
)
def render_emails_docx(
    *,
    emails: Sequence[str],
    output_path: Union[str, Path] = "emails_result.docx",
    source_name: str = "document",
) -> Path:
    """Сохранение списка email в Word-документ."""
    from textalchemy.extract.emails import emails_to_docx

    return emails_to_docx(emails, source_name=source_name, output_path=output_path)


@operation(
    "render.emails.txt",
    input_type="list[str]",
    output_type="Path",
    input_param="emails",
    description="list[str] → TXT (email адреса в текстовый файл).",
    tags=["render", "emails"],
)
def render_emails_txt(
    *,
    emails: Sequence[str],
    output_path: Union[str, Path] = "emails_result.txt",
    source_name: str = "document",
) -> Path:
    """Сохранение списка email в текстовый файл."""
    from textalchemy.extract.emails import emails_to_text

    return emails_to_text(emails, source_name=source_name, output_path=output_path)


@operation(
    "render.emails.debug",
    input_type="str",
    output_type="Path",
    input_param="full_text",
    description="Распознанный текст → TXT (отладочный вывод).",
    tags=["render", "emails", "debug"],
)
def render_emails_debug(
    *,
    full_text: str,
    output_path: Union[str, Path] = "debug_recognized_text.txt",
    pdf_name: str = "unknown",
    total_pages: int = 0,
    text_pages: int = 0,
    ocr_pages: int = 0,
) -> Path:
    """Сохранение отладочного файла с полным распознанным текстом."""
    from textalchemy.extract.emails import save_debug_text

    return save_debug_text(
        full_text,
        pdf_name=pdf_name,
        total_pages=total_pages,
        text_pages=text_pages,
        ocr_pages=ocr_pages,
        output_path=output_path,
    )


__all__ = [
    "extract_emails",
    "render_emails_docx",
    "render_emails_txt",
    "render_emails_debug",
]
