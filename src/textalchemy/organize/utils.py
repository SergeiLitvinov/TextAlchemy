"""Legacy-алиасы для organize.utils. Реализация в ``core.io``."""

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

__all__ = [
    "calculate_file_hash",
    "find_duplicates",
    "validate_pdf",
    "get_file_info",
    "list_files",
    "create_zip_archive",
    "sanitize_path",
    "ensure_folder",
    "progress_bar",
]
