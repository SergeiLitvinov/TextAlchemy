"""Единые хеш-утилиты.

Раньше было две копии (``core.file_utils.compute_file_hash`` и
``organize.utils.calculate_file_hash`` с md5) — здесь одна.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def compute_file_hash(path: str | Path, algorithm: str = "sha256", chunk: int = 65536) -> str:
    """SHA-256/MD5/etc. от файла. ``FileNotFoundError`` если файла нет."""
    p = Path(path)
    h = hashlib.new(algorithm)
    with open(p, "rb") as f:
        for piece in iter(lambda: f.read(chunk), b""):
            h.update(piece)
    return h.hexdigest()


__all__ = ["compute_file_hash"]
