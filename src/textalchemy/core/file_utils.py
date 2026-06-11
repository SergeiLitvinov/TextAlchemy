"""Legacy-алиасы. Реализация в ``core.io`` и ``core.hashing``."""
from textalchemy.core.hashing import compute_file_hash
from textalchemy.core.io import (
    ensure_dir,
    read_text_file,
    sanitize_filename,
    write_text_file,
)
from textalchemy.core.io import (
    find_duplicates_by_paths as find_duplicates,
)

__all__ = [
    "compute_file_hash",
    "ensure_dir",
    "find_duplicates",
    "read_text_file",
    "sanitize_filename",
    "write_text_file",
]
