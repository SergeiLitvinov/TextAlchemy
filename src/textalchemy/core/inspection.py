"""File inspection facade; legacy application JSON remains application-owned."""

from pathlib import Path

from opendoc_formats.support.inspection import DocumentComparison, DocumentInspection, compare_inspections, inspect_document_model
from opendoc_formats.support.inspection import inspect_path as _inspect_path


def inspect_path(path: str | Path) -> DocumentInspection:
    if Path(path).suffix.lower() == ".json":
        from textalchemy.core.document_codec import load_document

        return inspect_document_model(load_document(path), source_path=Path(path), source_format="document-model-json")
    return _inspect_path(path)


__all__ = ["DocumentComparison", "DocumentInspection", "compare_inspections", "inspect_document_model", "inspect_path"]
