"""Постраничный рендер документов для визуального preview.

Чтение PDF и офисная конвертация выполняются OpenDoc Formats.
Кэш страниц и промежуточного PDF живёт в каталоге preview внутри задачи,
поэтому удаляется вместе с задачей по TTL.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from textalchemy.core.io import atomic_write_bytes, atomic_write_text

DEFAULT_PREVIEW_DPI = 110
MAX_PREVIEW_DPI = 200

def libreoffice_path() -> Optional[str]:
    """Путь к headless LibreOffice или ``None``, если он недоступен."""
    from opendoc_formats.office import find_libreoffice

    executable = find_libreoffice()
    return str(executable) if executable else None


def convert_to_pdf(source: Path, output_pdf: Path) -> bool:
    """Конвертировать офисный документ в PDF через headless LibreOffice."""
    from opendoc_formats.errors import NativeAccessError
    from opendoc_formats.office import convert_office_to_pdf

    try:
        convert_office_to_pdf(source, output_pdf)
        return True
    except (NativeAccessError, OSError):
        return False


def pdf_page_count(pdf: Path) -> int:
    """Число страниц PDF-файла."""
    from opendoc_formats.pdf import PdfDocument

    with PdfDocument(pdf) as document:
        return document.page_count


def render_pdf_page_png(pdf: Path, page_index: int, *, dpi: int = DEFAULT_PREVIEW_DPI) -> Optional[bytes]:
    """PNG-байты страницы PDF (0-based индекс) или ``None``."""
    from opendoc_formats.pdf import PdfDocument

    dpi = max(1, min(int(dpi), MAX_PREVIEW_DPI))
    try:
        with PdfDocument(pdf) as document:
            if page_index < 0 or page_index >= document.page_count:
                return None
            return document.render_page(page_index, dpi=dpi).png
    except Exception:  # noqa: BLE001 - повреждённые PDF не должны ронять preview
        return None


def ensure_pdf(preview_dir: Path, source_file: Path, side: str) -> Optional[Path]:
    """Вернуть PDF для рендера; для офисных форматов конвертирует и кэширует."""
    if source_file.suffix.lower() == ".pdf":
        return source_file
    cached = preview_dir / f"{side}.pdf"
    if cached.is_file():
        return cached
    if convert_to_pdf(source_file, cached):
        return cached
    return None


def cached_page_count(preview_dir: Path, source_file: Path, side: str) -> int:
    """Число страниц документа с кэшированием в каталоге preview."""
    count_file = preview_dir / f"{side}-pages"
    if count_file.is_file():
        try:
            cached_count = int(count_file.read_text(encoding="utf-8").strip())
            if cached_count > 0:
                return cached_count
        except (OSError, ValueError):
            pass
    pdf = ensure_pdf(preview_dir, source_file, side)
    count = pdf_page_count(pdf) if pdf is not None else 0
    if count > 0:
        try:
            atomic_write_text(count_file, str(count), encoding="utf-8")
        except OSError:
            pass
    return count


def cached_page_png(
    preview_dir: Path,
    source_file: Path,
    side: str,
    page_index: int,
    *,
    dpi: int = DEFAULT_PREVIEW_DPI,
) -> Optional[bytes]:
    """PNG-байты страницы с кэшированием в каталоге preview."""
    dpi = max(1, min(int(dpi), MAX_PREVIEW_DPI))
    # DPI is part of the representation.  Without it, the first request
    # permanently determined the resolution returned to every later caller.
    png_path = preview_dir / f"{side}-{page_index}-{dpi}dpi.png"
    if png_path.is_file():
        try:
            return png_path.read_bytes()
        except OSError:
            pass
    pdf = ensure_pdf(preview_dir, source_file, side)
    if pdf is None:
        return None
    data = render_pdf_page_png(pdf, page_index, dpi=dpi)
    if data is None:
        return None
    try:
        atomic_write_bytes(png_path, data)
    except OSError:
        pass
    return data


__all__ = [
    "DEFAULT_PREVIEW_DPI",
    "MAX_PREVIEW_DPI",
    "cached_page_count",
    "cached_page_png",
    "convert_to_pdf",
    "ensure_pdf",
    "libreoffice_path",
    "pdf_page_count",
    "render_pdf_page_png",
]
