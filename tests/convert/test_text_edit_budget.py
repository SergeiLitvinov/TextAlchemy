"""Word-edit budgets are exact within the threshold and bounded in resource use."""

from itertools import product

import pytest

from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.text_edit_budget import bounded_word_distance
from textalchemy.core.text_quality_policy import TextPreservationPolicy


def _reference(left, right):
    matrix = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for row in range(len(left) + 1):
        matrix[row][0] = row
    for column in range(len(right) + 1):
        matrix[0][column] = column
    for row in range(1, len(left) + 1):
        for column in range(1, len(right) + 1):
            matrix[row][column] = min(matrix[row - 1][column] + 1, matrix[row][column - 1] + 1,
                                      matrix[row - 1][column - 1] + (left[row - 1] != right[column - 1]))
    return matrix[-1][-1]


def test_banded_distance_against_full_matrix_for_all_short_sequences():
    sequences = [list(sequence) for size in range(4) for sequence in product("ab", repeat=size)]
    for left, right in product(sequences, repeat=2):
        expected = _reference(left, right)
        for limit in range(4):
            distance, verified = bounded_word_distance(left, right, limit)
            assert verified
            assert distance == (expected if expected <= limit else None), (left, right, limit)


@pytest.mark.parametrize("before, after, edits", [
    ("one two", "one three", 1), ("one two", "one", 1), ("one", "one two", 1),
    ("one two", "two one", 2), ("same same", "same", 1), ("word!", "word", 1),
])
def test_budget_detects_edits_and_reports_only_proven_counts(tmp_path, before, after, edits):
    from textalchemy.core.document_model import DocumentModel, Paragraph, Section, TextRun
    from textalchemy.core.inspection import compare_inspections, inspect_document_model

    def inspection(text):
        return inspect_document_model(DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun(text)])])]))

    comparison = compare_inspections(inspection(before), inspection(after))
    for limit in [edits - 1, edits]:
        report = ConversionReport(tmp_path / "output.json")
        assert TextPreservationPolicy("flow", limit).evaluate(report, comparison) is (limit >= edits)
        gate = report.metrics["text_quality_gate"]
        assert gate["text_edits"] == (edits if limit >= edits else None)
        assert gate["text_edits_lower_bound"] == edits


def test_work_limit_returns_unknown_not_false_zero(monkeypatch):
    monkeypatch.setattr("textalchemy.core.text_edit_budget.MAX_DISTANCE_CELLS", 1)
    assert bounded_word_distance(list("abc"), list("def"), 3) == (None, False)


@pytest.mark.parametrize("limit", [-1, True, 1.5])
def test_invalid_budgets_are_rejected(limit):
    with pytest.raises(ValueError):
        TextPreservationPolicy("flow", limit)


def test_token_inventory_is_bounded_and_equal_large_text_can_still_pass(tmp_path, monkeypatch):
    from textalchemy.core.text_edit_budget import evaluate_text_edit_budget
    from textalchemy.core.text_flow import TextFlowFingerprint

    monkeypatch.setattr("textalchemy.core.text_flow.MAX_TEXT_TOKENS", 2)
    flow = TextFlowFingerprint()
    flow.add("one two three")
    snapshot = flow.to_dict()
    assert snapshot["token_count"] == 3
    assert snapshot["tokens"] is None
    report = ConversionReport(tmp_path / "output.json")
    assert evaluate_text_edit_budget(report, snapshot, snapshot, True, 1)
    changed = {**snapshot, "sha256": "different"}
    assert not evaluate_text_edit_budget(report, snapshot, changed, True, 1)
    assert report.metrics["text_quality_gate"]["verified"] is False


@pytest.mark.parametrize("limit", [0, 1])
def test_cli_budget_controls_publication_after_silent_substitution(tmp_path, monkeypatch, capsys, limit):
    import json

    from textalchemy.__main__ import main
    from textalchemy.convert.docx_writer import write_docx_model
    from textalchemy.core.document_model import TextRun

    source, target = tmp_path / "source.txt", tmp_path / "output.docx"
    source.write_text("Original text", encoding="utf-8")
    target.write_bytes(b"previous")

    def export(model, output):
        model.sections[0].blocks[0].content = [TextRun("Replaced text")]
        return write_docx_model(model, output)

    monkeypatch.setattr("textalchemy.convert.executor._write_docx", export)
    assert main(["convert-file", str(source), str(target), "--max-text-edits", str(limit), "--json"]) == (0 if limit else 1)
    gate = json.loads(capsys.readouterr().out)["metrics"]["text_quality_gate"]
    assert gate["accepted"] is bool(limit)
    assert (target.read_bytes() != b"previous") is bool(limit)
