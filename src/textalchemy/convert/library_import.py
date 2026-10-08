"""Translate public adapter diagnostics into the application's route report."""

from pathlib import Path
from typing import Callable

from opendoc_formats import ImportOptions, read_document
from opendoc_formats.text_profile import TextProfile
from opendoc_model import DocumentModel

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity


def import_document(
    source: Path | DocumentModel, output: Path, format_id: str, *,
    txt_encoding: str = "auto", cancelled: Callable[[], bool] | None = None,
) -> tuple[DocumentModel | None, ConversionReport]:
    if not isinstance(source, Path):
        raise TypeError("Document importer requires a path")
    result = read_document(source, format_id=format_id, options=ImportOptions(
        txt_profile=TextProfile(txt_encoding), cancelled=cancelled))
    report = ConversionReport(output)
    for issue in result.issues:
        message = issue.message
        if issue.code == "import.txt-encoding":
            message = (
                "Не удалось прочитать TXT с выбранной кодировкой. В экспертном режиме укажите кодировку исходного TXT; "
                "для старых русскоязычных файлов попробуйте Windows-1251. " + message
            )
        report.add(issue.severity, issue.code, message, issue.location)
    report.metrics.update(
        assessment_complete=result.assessment_complete, lossless=result.lossless,
        import_diagnostics=[{
            "code": issue.code, "severity": issue.severity.value, "message": issue.message,
            "location": issue.location, "reason": issue.reason, "measurement": issue.measurement,
        } for issue in result.issues],
    )
    if not result.success and not any(issue.severity is IssueSeverity.ERROR for issue in report.issues):
        report.add(IssueSeverity.ERROR, "import.invalid-result", "Adapter did not return a valid document")
    return result.document, report


def inspect_source(source: Path, txt_encoding: str):
    """Inspect the same explicit TXT profile that will be used by conversion."""
    from textalchemy.core.inspection import inspect_document_model, inspect_path

    if source.suffix.lower() != ".txt" or txt_encoding == "auto":
        return inspect_path(source)
    result = read_document(source, format_id="txt", options=ImportOptions(txt_profile=TextProfile(txt_encoding)))
    if not result.success or result.document is None:
        raise ValueError("; ".join(issue.message for issue in result.issues))
    inspection = inspect_document_model(result.document, source_path=source, source_format="txt")
    # Plain text has no measured pages, regardless of model defaults.
    inspection.pages.clear()
    inspection.metrics.pop("pages", None)
    return inspection
