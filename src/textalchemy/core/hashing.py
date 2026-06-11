"""Единые хеш-утилиты.

Раньше было две копии (``core.file_utils.compute_file_hash`` с sha256 и
``organize.utils.calculate_file_hash`` с md5) — здесь одна. Реализация
живёт в ``core.io.compute_hash``; этот модуль — тонкий алиас.
"""
from __future__ import annotations

from textalchemy.core.io import compute_hash


def compute_file_hash(path, algorithm: str = "sha256", chunk: int = 65536) -> str:
    """Алиас ``compute_hash`` (legacy-имя)."""
    return compute_hash(path, algorithm=algorithm, chunk=chunk)


__all__ = ["compute_file_hash"]
