"""Прикладная стадия проверки PDF через публичный API форматной библиотеки."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

from opendoc_formats.errors import NativeAccessError, OperationCancelledError
from opendoc_formats.pdf import PdfDocument

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity


def verify_pdf_output(
    path: Path,
    report: ConversionReport,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    """Проверить открытие и чтение всех страниц до атомарной публикации файла.

    Проверка не измеряет визуальное сходство, шрифты или редактируемость объектов.
    Ограничения чтения и освобождение PDF-контекста принадлежат библиотеке.
    """
    metrics = {
        "stage": "verify",
        "verifier": "opendoc_formats.pdf.PdfDocument",
        "scope": ["open", "all_page_text", "page_geometry"],
        "verified": False,
        "pages": None,
        "checked_pages": 0,
    }
    report.metrics["pdf_verification"] = metrics
    try:
        with PdfDocument(path, cancelled=cancelled) as document:
            metrics["pages"] = document.page_count
            for index in range(document.page_count):
                page = document.page_info(index)
                if not all(math.isfinite(value) and value > 0 for value in (page.width, page.height)):
                    raise ValueError(f"Недопустимый размер страницы PDF: {index + 1}")
                metrics["checked_pages"] += 1
        if cancelled is not None and cancelled():
            raise OperationCancelledError("Проверка PDF отменена")
        metrics["verified"] = True
    except OperationCancelledError:
        metrics["error_code"] = "cancelled"
        report.metrics["cancelled"] = True
        report.add(IssueSeverity.ERROR, "cancelled", "Проверка PDF отменена; результат не опубликован")
    except (NativeAccessError, OSError, ValueError) as error:
        metrics["error_code"] = getattr(error, "code", "pdf-verification")
        report.add(IssueSeverity.ERROR, "pdf-verification", f"Не удалось проверить записанный PDF: {error}")


__all__ = ["verify_pdf_output"]
