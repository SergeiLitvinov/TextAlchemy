"""Стадия ingest: файл → Document.

Единственная ответственность — открыть файл, посчитать хеш, определить формат.
Никакого чтения содержимого на этой стадии.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from textalchemy.core.registry import operation
from textalchemy.core.types import Document


@operation(
    "ingest.file",
    input_type="path",
    output_type="Document",
    input_param="path",
    description="Открыть файл и собрать Document (хеш + формат).",
    tags=["ingest", "io"],
)
def ingest_file(*, path: Union[str, Path]) -> Document:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    # Document.from_path лениво вычисляет sha256 в __post_init__.
    return Document.from_path(p)


__all__ = ["ingest_file"]
