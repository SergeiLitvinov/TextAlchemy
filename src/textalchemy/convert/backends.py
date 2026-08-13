"""Typed adapters between importer/exporter protocols and the executor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from textalchemy.convert.protocols import ConversionValue
from textalchemy.convert.stages import StageContext, StageKind, StageResult
from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import DocumentModel

ImporterFunction = Callable[[Path], DocumentModel]
ExporterFunction = Callable[[DocumentModel, Path], ConversionReport]
ConverterFunction = Callable[[Path, Path], ConversionReport]


@dataclass(frozen=True)
class ImporterBackend:
    id: str
    importer: ImporterFunction
    kind: StageKind = StageKind.PARSE

    def read(self, input_path: Path) -> DocumentModel:
        return self.importer(input_path)

    def execute(
        self,
        value: ConversionValue,
        _output_path: Path,
    ) -> tuple[DocumentModel, None]:
        return self.read(_require_path(value)), None

    def execute_stage(self, value: ConversionValue, context: StageContext) -> StageResult:
        return StageResult(self.read(_require_path(value)))


@dataclass(frozen=True)
class ExporterBackend:
    id: str
    exporter: ExporterFunction
    kind: StageKind = StageKind.SERIALIZE

    def write(self, document: DocumentModel, output_path: Path) -> ConversionReport:
        return self.exporter(document, output_path)

    def execute(
        self,
        value: ConversionValue,
        output_path: Path,
    ) -> tuple[Path, ConversionReport]:
        report = self.write(_require_model(value), output_path)
        return report.output_path, report

    def execute_stage(self, value: ConversionValue, context: StageContext) -> StageResult:
        report = self.write(_require_model(value), context.output_path)
        return StageResult(report.output_path, report)


@dataclass(frozen=True)
class PathConverterBackend:
    id: str
    converter: ConverterFunction
    kind: StageKind = StageKind.SERIALIZE

    def convert(self, input_path: Path, output_path: Path) -> ConversionReport:
        return self.converter(input_path, output_path)

    def execute(
        self,
        value: ConversionValue,
        output_path: Path,
    ) -> tuple[Path, ConversionReport]:
        report = self.convert(_require_path(value), output_path)
        return report.output_path, report

    def execute_stage(self, value: ConversionValue, context: StageContext) -> StageResult:
        report = self.convert(_require_path(value), context.output_path)
        return StageResult(report.output_path, report)


def _require_path(value: ConversionValue) -> Path:
    if not isinstance(value, Path):
        raise TypeError(f"conversion backend expected Path, got {type(value).__name__}")
    return value


def _require_model(value: ConversionValue) -> DocumentModel:
    if not isinstance(value, DocumentModel):
        raise TypeError(f"conversion backend expected DocumentModel, got {type(value).__name__}")
    return value


__all__ = ["ExporterBackend", "ImporterBackend", "PathConverterBackend"]
