"""Tests for public conversion protocols and legacy result compatibility."""

from pathlib import Path

from textalchemy.convert import (
    ConversionBackend,
    ConversionResult,
    DocumentExporter,
    DocumentImporter,
    ExporterBackend,
    ImporterBackend,
    PathConverter,
    PathConverterBackend,
)
from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import DocumentModel


def _read_model(_input_path: Path) -> DocumentModel:
    return DocumentModel()


def _write_model(_document: DocumentModel, output_path: Path) -> ConversionReport:
    return ConversionReport(output_path)


def _convert_path(_input_path: Path, output_path: Path) -> ConversionReport:
    return ConversionReport(output_path)


def test_legacy_result_is_a_structured_report(tmp_path):
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.docx"

    result = ConversionResult(input_path, output_path, False, "engine failed")

    assert isinstance(result, ConversionReport)
    assert not result.success
    assert result.error == "engine failed"
    assert result.issues[0].feature == "conversion"
    assert result.to_dict()["input_path"] == str(input_path)
    assert result.to_dict()["error"] == "engine failed"


def test_legacy_success_result_keeps_compatibility(tmp_path):
    result = ConversionResult(tmp_path / "input.pdf", tmp_path / "output.docx", True)

    assert result.success
    assert result.lossless
    assert result.error is None


def test_typed_adapters_implement_public_protocols():
    importer = ImporterBackend("test.import", _read_model)
    exporter = ExporterBackend("test.export", _write_model)
    converter = PathConverterBackend("test.convert", _convert_path)

    assert isinstance(importer, DocumentImporter)
    assert isinstance(importer, ConversionBackend)
    assert isinstance(exporter, DocumentExporter)
    assert isinstance(exporter, ConversionBackend)
    assert isinstance(converter, PathConverter)
    assert isinstance(converter, ConversionBackend)
