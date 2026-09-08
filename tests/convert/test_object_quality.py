"""Object budgets verify serialized artifacts, not exporter declarations."""

import pytest

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import DocumentModel, Paragraph, Section, TextRun
from textalchemy.core.object_quality_policy import ObjectLossPolicy
from textalchemy.core.types import DocFormat


@pytest.mark.parametrize("limit", [-1, True, 0.5])
def test_reject_invalid_object_budget(limit):
    with pytest.raises(ValueError):
        ObjectLossPolicy(limit)


@pytest.mark.parametrize("limit, accepted", [(0, False), (1, True)])
def test_silent_export_loss_is_checked_before_publication(tmp_path, monkeypatch, limit, accepted):
    from textalchemy.convert.docx_writer import write_docx_model
    from textalchemy.core.document_codec import save_document

    source, target = tmp_path / "source.json", tmp_path / "target.docx"
    save_document(DocumentModel(sections=[Section(blocks=[
        Paragraph(content=[TextRun("Lost")]), Paragraph(content=[TextRun("Kept")]),
    ])]), source)
    target.write_bytes(b"previous result")

    def lossy_export(model, output):
        model.sections[0].blocks.pop(0)
        return write_docx_model(model, output)

    monkeypatch.setattr("textalchemy.convert.executor._write_docx", lossy_export)
    report = ConversionExecutor().execute(ConversionRequest(
        source, target, DocFormat.MODEL, DocFormat.DOCX, object_loss_policy=ObjectLossPolicy(limit),
    ))
    assert report.success is accepted
    gate = report.metrics["object_quality_gate"]
    assert gate["verified"] is True
    assert gate["lost_objects"] == 1
    assert gate["accepted"] is accepted
    assert (target.read_bytes() != b"previous result") is accepted
    assert not list(tmp_path.glob(".textalchemy-*"))


@pytest.mark.parametrize("text, target_format, suffix", [
    ("Repeated\nRepeated", DocFormat.DOCX, ".docx"),
    ("Unique", DocFormat.HTML, ".html"),
])
def test_unverifiable_budget_never_publishes_output(tmp_path, text, target_format, suffix):
    source, target = tmp_path / "source.txt", tmp_path / f"target{suffix}"
    source.write_text(text, encoding="utf-8")
    report = ConversionExecutor().execute(ConversionRequest(
        source, target, DocFormat.TXT, target_format, object_loss_policy=ObjectLossPolicy(100),
    ))
    assert not report.success
    assert not target.exists()
    gate = report.metrics["object_quality_gate"]
    assert gate["verified"] is False
    assert gate["lost_objects"] is None
    assert gate["reason"] in {"uncertain-matching", "unavailable"}


def test_unique_txt_docx_conversion_passes_object_budget(tmp_path):
    source, target = tmp_path / "source.txt", tmp_path / "target.docx"
    source.write_text("First\nSecond", encoding="utf-8")
    report = ConversionExecutor().execute(ConversionRequest(
        source, target, DocFormat.TXT, DocFormat.DOCX, object_loss_policy=ObjectLossPolicy(0),
    ))
    assert report.success
    assert target.is_file()
    assert report.metrics["object_quality_gate"]["lost_objects"] == 0


def test_inspection_exception_fails_closed(tmp_path, monkeypatch):
    from textalchemy.convert.object_quality import check_object_quality

    def broken_inspector(path):
        raise RuntimeError("Unreadable result")

    monkeypatch.setattr("textalchemy.convert.object_quality.inspect_path", broken_inspector)
    report = ConversionReport(tmp_path / "output.docx")
    check_object_quality(tmp_path / "source.txt", report.output_path, report, ObjectLossPolicy())
    assert not report.success
    assert report.metrics["object_quality_gate"]["reason"] == "unavailable"


def test_cli_object_budget_is_independent_of_diagnostic_budget(tmp_path, capsys):
    import json

    from textalchemy.__main__ import main

    source, target = tmp_path / "source.txt", tmp_path / "target.docx"
    source.write_text("Unique", encoding="utf-8")
    assert main(["convert-file", str(source), str(target), "--max-lost-objects", "0", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["metrics"]["object_quality_gate"]["accepted"] is True
    assert "quality_gate" not in report["metrics"]
