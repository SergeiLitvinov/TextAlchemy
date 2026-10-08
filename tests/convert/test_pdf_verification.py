"""Независимое чтение PDF перед публикацией и сохранение прежнего результата."""

from pathlib import Path
from typing import Any
from unicodedata import normalize

import pytest
from opendoc_formats.errors import OperationCancelledError
from opendoc_formats.pdf import PdfDocument

from textalchemy.convert import verification
from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.conversion_graph import CapabilityRegistry, ConverterCapabilities, DocumentFeature, FeatureSupport
from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.types import DocFormat


def _pdf_bytes() -> bytes:
    """Две настоящие страницы позволяют проверить чтение не только первой."""
    import fitz

    with fitz.open() as document:
        for text in ("First verified page", "Second verified page"):
            document.new_page().insert_text((72, 72), text)
        return document.tobytes()


def _executor(data: bytes) -> ConversionExecutor:
    registry = CapabilityRegistry()
    registry.register(
        ConverterCapabilities(
            "fixture.pdf",
            DocFormat.TXT,
            DocFormat.PDF,
            frozenset({ConversionMode.BALANCED}),
            {DocumentFeature.TEXT: FeatureSupport.EXACT},
        )
    )

    def write(value: Any, output: Path) -> tuple[Path, ConversionReport]:
        output.write_bytes(data)
        return output, ConversionReport(output)

    return ConversionExecutor(registry=registry, handlers={"fixture.pdf": write})


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("valid", [False, True])
def test_pdf_is_verified_without_quality_policy_before_publication(tmp_path: Path, existing: bool, valid: bool) -> None:
    source, output = tmp_path / "source.txt", tmp_path / "result.pdf"
    source.write_text("Unchanged source", encoding="utf-8")
    if existing:
        output.write_bytes(b"Previous result")
    data = _pdf_bytes() if valid else b"Exporter claims success but this is not PDF"
    report = _executor(data).execute(ConversionRequest(source, output, DocFormat.TXT, DocFormat.PDF))
    assert report.success is valid
    assert report.output_path == output
    metrics = report.metrics["pdf_verification"]
    assert metrics["verified"] is valid
    if valid:
        assert metrics["pages"] == metrics["checked_pages"] == 2
        assert output.read_bytes() == data
    else:
        assert any(issue.feature == "pdf-verification" for issue in report.issues)
        if existing:
            assert output.read_bytes() == b"Previous result"
        else:
            assert not output.exists()
    assert source.read_text(encoding="utf-8") == "Unchanged source"
    assert not list(tmp_path.glob(".textalchemy-*"))


@pytest.mark.parametrize("failure", ["second_page", "cancel"])
def test_pdf_late_verification_failure_keeps_previous_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    source, output = tmp_path / "source.txt", tmp_path / "result.pdf"
    source.write_text("Source", encoding="utf-8")
    output.write_bytes(b"Previous result")
    opened: list[PdfDocument] = []

    class FailingPdf(PdfDocument):
        def __enter__(self) -> PdfDocument:
            opened.append(self)
            return super().__enter__()

        def page_info(self, index: int) -> Any:
            if index == 1:
                if failure == "cancel":
                    raise OperationCancelledError("Cancelled during page reading")
                raise ValueError("Second page cannot be read")
            return super().page_info(index)

    monkeypatch.setattr(verification, "PdfDocument", FailingPdf)
    report = _executor(_pdf_bytes()).execute(ConversionRequest(source, output, DocFormat.TXT, DocFormat.PDF))
    assert not report.success
    assert report.metrics["pdf_verification"]["checked_pages"] == 1
    assert report.metrics["pdf_verification"]["verified"] is False
    assert report.metrics.get("cancelled", False) is (failure == "cancel")
    assert opened and opened[0].closed
    assert output.read_bytes() == b"Previous result"
    assert not list(tmp_path.glob(".textalchemy-*"))


def test_real_txt_pdf_route_has_independent_verify_stage(tmp_path: Path) -> None:
    source, output = tmp_path / "source.txt", tmp_path / "result.pdf"
    source.write_text("Real conversion and independent verification", encoding="utf-8")
    report = ConversionExecutor().execute(ConversionRequest(source, output, DocFormat.TXT, DocFormat.PDF))
    assert report.success, report.to_dict()
    assert report.metrics["executed_steps"] == ["txt.model", "model.pdf"]
    assert report.metrics["pdf_verification"]["stage"] == "verify"
    assert report.metrics["pdf_verification"]["verified"] is True
    with PdfDocument(output) as document:
        assert "Real conversion and independent verification" in normalize("NFKC", document.page_info(0).text)
    assert not list(tmp_path.glob(".textalchemy-*"))
