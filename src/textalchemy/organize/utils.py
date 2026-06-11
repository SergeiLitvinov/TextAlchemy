"""Legacy-алиасы для organize.utils. Реализация в ``core.io``."""
from pathlib import Path

from textalchemy.core.io import compute_hash as calculate_file_hash
from textalchemy.core.io import (
    create_zip_archive,
    ensure_folder,
    get_file_info,
    list_files,
    progress_bar,
    sanitize_path,
    validate_pdf,
)
from textalchemy.core.io import (
    find_duplicates_in_folder as find_duplicates,
)


def get_file_content(file_path) -> str:
    """Извлечь текст из файла по расширению. Legacy-обёртка.

    Использует новые ридеры из ``textalchemy.formats.*``. Возвращает только
    ``plain``-текст (без структурных блоков), как и старая версия.
    """
    fp = Path(file_path)
    ext = fp.suffix.lower()
    if ext == ".pdf":
        from textalchemy.formats.pdf import read_pdf
        return read_pdf(str(fp)).plain
    if ext == ".docx":
        from textalchemy.formats.docx import read_docx
        return read_docx(fp).plain
    if ext in (".txt", ".doc"):
        from textalchemy.formats.txt import read_txt
        return read_txt(fp).plain
    if ext == ".djvu":
        from textalchemy.formats.txt import read_djvu
        return read_djvu(fp).plain
    return ""


__all__ = [
    "calculate_file_hash",
    "find_duplicates",
    "validate_pdf",
    "get_file_info",
    "list_files",
    "create_zip_archive",
    "sanitize_path",
    "ensure_folder",
    "get_file_content",
    "progress_bar",
]
