"""Постраничный рендер документов для визуального preview.

PDF рендерится напрямую через PyMuPDF; DOCX/PPTX/ODT и другие офисные
форматы конвертируются в PDF через headless LibreOffice (если он доступен).
Кэш страниц и промежуточного PDF живёт в каталоге preview внутри задачи,
поэтому удаляется вместе с задачей по TTL.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from textalchemy.core.io import atomic_copy, atomic_write_bytes, atomic_write_text

DEFAULT_PREVIEW_DPI = 110
MAX_PREVIEW_DPI = 200

_LIBREOFFICE_CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.com",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.com",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/libreoffice",
    "/usr/bin/soffice",
    "/usr/local/bin/soffice",
    "/opt/libreoffice/program/soffice",
)


def libreoffice_path() -> Optional[str]:
    """Путь к headless LibreOffice или ``None``, если он недоступен."""
    for candidate in _LIBREOFFICE_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("soffice") or shutil.which("libreoffice")


def convert_to_pdf(source: Path, output_pdf: Path) -> bool:
    """Конвертировать офисный документ в PDF через headless LibreOffice."""
    executable = libreoffice_path()
    if executable is None or not source.is_file():
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="ta-lo-") as tmp:
            profile = Path(tmp) / "profile"
            profile.mkdir()
            profile_url = f"file:///{profile.as_posix()}"
            result = subprocess.run(
                [
                    executable,
                    "--headless",
                    f"-env:UserInstallation={profile_url}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmp,
                    str(source),
                ],
                capture_output=True,
                timeout=180,
            )
            if result.returncode != 0:
                return False
            produced = Path(tmp) / f"{source.stem}.pdf"
            if not produced.is_file():
                return False
            output_pdf.parent.mkdir(parents=True, exist_ok=True)
            # ``tmp`` and the preview cache may live on different filesystems,
            # where ``os.replace`` fails with EXDEV.  Copy through a sibling
            # partial file so publishing the cached PDF remains atomic.
            atomic_copy(produced, output_pdf)
            return True
    except (OSError, subprocess.SubprocessError):
        return False


def pdf_page_count(pdf: Path) -> int:
    """Число страниц PDF-файла."""
    import fitz

    with fitz.open(pdf) as document:
        return document.page_count


def render_pdf_page_png(pdf: Path, page_index: int, *, dpi: int = DEFAULT_PREVIEW_DPI) -> Optional[bytes]:
    """PNG-байты страницы PDF (0-based индекс) или ``None``."""
    import fitz

    dpi = max(1, min(int(dpi), MAX_PREVIEW_DPI))
    try:
        with fitz.open(pdf) as document:
            if page_index < 0 or page_index >= document.page_count:
                return None
            pixmap = document.load_page(page_index).get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
            return pixmap.tobytes("png")
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
