"""Exact text preservation detects changes hidden by object/length counts."""

import pytest

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import DocumentModel, Paragraph, Section, Table, TableCell, TableRow, TextRun
from textalchemy.core.inspection import DocumentInspection, compare_inspections, inspect_document_model
from textalchemy.core.text_quality_policy import TextPreservationPolicy
from textalchemy.core.types import DocFormat


def _inspect(texts, nested=False):
    blocks = [Paragraph(content=[TextRun(text)]) for text in texts]
    if nested:
        blocks = [Table(rows=[TableRow(cells=[TableCell(blocks=blocks)])])]
    return inspect_document_model(DocumentModel(sections=[Section(blocks=blocks)]))


@pytest.mark.parametrize("before, after, accepted, unmatched", [
    (["First", "Second"], ["Second", "First", "Added"], True, 0),
    (["Same", "Same"], ["Same", "Same"], True, 0),
    (["Same", "Same"], ["Same"], False, 1),
    (["abcdef"], ["abc"], False, 1),
    (["abcdef"], ["ghijkl"], False, 1),
    (["First Second"], ["First", "Second"], False, 1),
    (["First", "Second"], ["FirstSecond"], False, 2),
    (["First "], ["First"], False, 1),
    ([""], [], True, 0),
])
@pytest.mark.parametrize("nested", [False, True])
def test_text_policy_is_exact_and_multiplicity_aware(tmp_path, before, after, accepted, unmatched, nested):
    report = ConversionReport(tmp_path / "result.json")
    comparison = compare_inspections(_inspect(before, nested), _inspect(after, nested))
    assert TextPreservationPolicy().evaluate(report, comparison) is accepted
    assert report.metrics["text_quality_gate"]["unmatched_source_paragraphs"] == unmatched


def test_unavailable_inventory_does_not_pass_as_empty_text(tmp_path):
    report = ConversionReport(tmp_path / "result.html")
    comparison = compare_inspections(_inspect(["Text"]), DocumentInspection(None, "html"))
    assert TextPreservationPolicy().evaluate(report, comparison) is False
    assert report.metrics["text_quality_gate"]["unmatched_source_paragraphs"] is None


def test_silent_same_length_replacement_does_not_overwrite_previous_result(tmp_path, monkeypatch):
    from textalchemy.convert.docx_writer import write_docx_model

    source, target = tmp_path / "input.txt", tmp_path / "result.docx"
    source.write_text("Original", encoding="utf-8")
    target.write_bytes(b"previous result")

    def changed_export(model, output):
        model.sections[0].blocks[0].content = [TextRun("Replaced")]
        return write_docx_model(model, output)

    monkeypatch.setattr("textalchemy.convert.executor._write_docx", changed_export)
    report = ConversionExecutor().execute(ConversionRequest(
        source, target, DocFormat.TXT, DocFormat.DOCX, text_preservation_policy=TextPreservationPolicy(),
    ))
    assert not report.success
    assert report.metrics["text_quality_gate"]["reason"] == "text-changed-or-removed"
    assert target.read_bytes() == b"previous result"
    assert not list(tmp_path.glob(".textalchemy-*"))


def test_cli_text_policy_is_independent(tmp_path, capsys):
    import json

    from textalchemy.__main__ import main

    source, target = tmp_path / "input.txt", tmp_path / "result.docx"
    source.write_text("Original", encoding="utf-8")
    assert main(["convert-file", str(source), str(target), "--require-unchanged-text", "--json"]) == 0
    metrics = json.loads(capsys.readouterr().out)["metrics"]
    assert metrics["text_quality_gate"]["accepted"] is True
    assert "object_quality_gate" not in metrics
