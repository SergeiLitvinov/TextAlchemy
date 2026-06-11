"""Стадия ingest: файл → Document.

Единственная ответственность — открыть файл, посчитать хеш, определить формат.
Никакого чтения содержимого на этой стадии.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from textalchemy.core.hashing import compute_file_hash
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
    doc = Document.from_path(p)
    return Document(
        path=doc.path,
        format=doc.format,
        size=doc.size,
        sha256=compute_file_hash(p, algorithm="sha256"),
    )


__all__ = ["ingest_file"]
