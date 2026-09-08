"""Text flow allows paragraph resegmentation, not changes to words or order."""

import pytest

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import DocumentModel, Paragraph, Section, Table, TableCell, TableRow, TextRun
from textalchemy.core.inspection import compare_inspections, inspect_document_model
from textalchemy.core.text_quality_policy import TextPreservationPolicy, resolve_text_policy
from textalchemy.core.types import DocFormat


def _inspect(texts, nested):
    blocks = [Paragraph(content=[TextRun(text)]) for text in texts]
    if nested:
        blocks = [Table(rows=[TableRow(cells=[TableCell(blocks=blocks)])])]
    return inspect_document_model(DocumentModel(sections=[Section(blocks=blocks)]))


@pytest.mark.parametrize("before, after, accepted", [
    (["First Second"], ["First", "Second"], True),
    (["First", "Second"], ["First Second"], True),
    ([" First\tSecond\nThird "], ["First Second Third"], True),
    (["First\u00a0Second"], ["First Second"], True),
    (["First", "Second"], ["Second", "First"], False),
    (["Same", "Same"], ["Same"], False),
    (["Original"], ["Replaced"], False),
    (["First"], ["first"], False),
    (["First!"], ["First"], False),
    (["First"], ["First Added"], False),
    (["word"], ["wo", "rd"], False),
    (["long-", "word"], ["longword"], False),
    (["", "  "], [], True),
])
@pytest.mark.parametrize("nested", [False, True])
def test_flow_normalizes_only_whitespace_and_paragraph_boundaries(tmp_path, before, after, accepted, nested):
    comparison = compare_inspections(_inspect(before, nested), _inspect(after, nested))
    report = ConversionReport(tmp_path / "output.json")
    assert TextPreservationPolicy("flow").evaluate(report, comparison) is accepted
    assert report.metrics["text_quality_gate"]["verified"] is True


@pytest.mark.parametrize("mode, accepted", [("paragraphs", False), ("flow", True)])
def test_serialized_paragraph_split_respects_selected_mode(tmp_path, monkeypatch, mode, accepted):
    from textalchemy.convert.docx_writer import write_docx_model

    source, target = tmp_path / "input.txt", tmp_path / "output.docx"
    source.write_text("First Second", encoding="utf-8")
    target.write_bytes(b"previous result")

    def export(model, output):
        model.sections[0].blocks = [Paragraph(content=[TextRun(text)]) for text in ["First", "Second"]]
        return write_docx_model(model, output)

    monkeypatch.setattr("textalchemy.convert.executor._write_docx", export)
    report = ConversionExecutor().execute(ConversionRequest(
        source, target, DocFormat.TXT, DocFormat.DOCX, text_preservation_policy=TextPreservationPolicy(mode),
    ))
    assert report.success is accepted
    assert (target.read_bytes() != b"previous result") is accepted
    assert not list(tmp_path.glob(".textalchemy-*"))


def test_flow_without_measurement_is_unavailable(tmp_path):
    source, target = _inspect(["Text"], False), _inspect(["Text"], False)
    target.metadata.pop("text_flow")
    report = ConversionReport(tmp_path / "output.json")
    assert not TextPreservationPolicy("flow").evaluate(report, compare_inspections(source, target))
    assert report.metrics["text_quality_gate"]["source_characters"] is None


def test_conflicting_modes_are_rejected():
    with pytest.raises(ValueError):
        resolve_text_policy(True, "flow")
    with pytest.raises(ValueError):
        resolve_text_policy(False, "invalid")


def test_cli_flow_mode(tmp_path, capsys):
    import json

    from textalchemy.__main__ import main

    source, target = tmp_path / "source.txt", tmp_path / "result.docx"
    source.write_text("First\nSecond", encoding="utf-8")
    assert main(["convert-file", str(source), str(target), "--text-preservation", "flow", "--json"]) == 0
    gate = json.loads(capsys.readouterr().out)["metrics"]["text_quality_gate"]
    assert gate["mode"] == "flow"
    assert gate["accepted"] is True
