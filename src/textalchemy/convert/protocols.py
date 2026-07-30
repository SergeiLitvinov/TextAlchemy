"""Public protocols for executable document conversion components."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, TypeAlias, runtime_checkable

from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import DocumentModel

ConversionValue: TypeAlias = Path | DocumentModel


@runtime_checkable
class DocumentImporter(Protocol):
    id: str

    def read(self, input_path: Path) -> DocumentModel:
        ...


@runtime_checkable
class DocumentExporter(Protocol):
    id: str

    def write(self, document: DocumentModel, output_path: Path) -> ConversionReport:
        ...


@runtime_checkable
class PathConverter(Protocol):
    id: str

    def convert(self, input_path: Path, output_path: Path) -> ConversionReport:
        ...


@runtime_checkable
class ConversionBackend(Protocol):
    id: str

    def execute(
        self,
        value: ConversionValue,
        output_path: Path,
    ) -> tuple[ConversionValue, ConversionReport | None]:
        ...


__all__ = [
    "ConversionBackend",
    "ConversionValue",
    "DocumentExporter",
    "DocumentImporter",
    "PathConverter",
]
