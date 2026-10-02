"""Inspect serialized emphasis, including partial losses and strict publication."""

import pytest

from textalchemy.convert.docx_writer import write_docx_model
from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.document_codec import save_document
from textalchemy.core.document_model import DocumentModel, Paragraph, Section, TextRun, TextStyle
from textalchemy.core.emphasis_quality import EmphasisInventory, EmphasisLossPolicy
from textalchemy.core.inspection import compare_inspections, inspect_document_model
from textalchemy.core.types import DocFormat


def emphasis_document():
    return DocumentModel(sections=[Section(blocks=[Paragraph(content=[
        TextRun('Test', TextStyle(bold=True, italic=True)), TextRun(' plain'),
    ])])])


@pytest.mark.parametrize('limit', [-1, True, 0.1, '0'])
def test_invalid_emphasis_limit(limit):
    with pytest.raises(ValueError):
        EmphasisLossPolicy(limit)


@pytest.mark.parametrize('limit,accepted', [(0, False), (3, False), (4, True)])
def test_real_docx_to_txt_emphasis_loss(tmp_path, limit, accepted):
    source, target = tmp_path / 'source.docx', tmp_path / 'target.txt'
    write_docx_model(emphasis_document(), source)
    target.write_text('previous', encoding='utf-8')
    report = ConversionExecutor().execute(ConversionRequest(
        source, target, DocFormat.DOCX, DocFormat.TXT, emphasis_loss_policy=EmphasisLossPolicy(limit),
    ))
    assert report.success is accepted, report.to_dict()
    assert report.metrics['emphasis_quality_gate']['changed_characters'] == 4
    assert (target.read_text(encoding='utf-8') != 'previous') is accepted
    assert not list(tmp_path.glob('.textalchemy-*'))


def test_emphasis_survives_two_docx_model_cycles(tmp_path):
    executor = ConversionExecutor()
    native = tmp_path / 'source.docx'
    write_docx_model(emphasis_document(), native)
    for cycle in range(2):
        model, result = tmp_path / f'model-{cycle}.json', tmp_path / f'result-{cycle}.docx'
        for before, after, a, b in ((native, model, DocFormat.DOCX, DocFormat.MODEL),
                                   (model, result, DocFormat.MODEL, DocFormat.DOCX)):
            report = executor.execute(ConversionRequest(before, after, a, b,
                emphasis_loss_policy=EmphasisLossPolicy(0)))
            assert report.success, report.to_dict()
            assert report.metrics['emphasis_quality_gate']['changed_characters'] == 0
        native = result


def test_run_splitting_whitespace_and_paragraph_boundaries_do_not_change_emphasis(tmp_path):
    from textalchemy.core.diagnostics import ConversionReport

    source = emphasis_document()
    target = DocumentModel(sections=[Section(blocks=[
        Paragraph(content=[TextRun('Te ', TextStyle(bold=True, italic=True))]),
        Paragraph(content=[TextRun('st', TextStyle(bold=True, italic=True)), TextRun('plain')]),
    ])])
    comparison = compare_inspections(inspect_document_model(source), inspect_document_model(target))
    report = ConversionReport(tmp_path / 'out.json')
    assert EmphasisLossPolicy(0).evaluate(report, comparison)


def test_text_change_cannot_pass_a_permissive_emphasis_budget(tmp_path, monkeypatch):
    source, target = tmp_path / 'source.json', tmp_path / 'result.docx'
    save_document(emphasis_document(), source)

    def change_text(model, path):
        model.sections[0].blocks[0].content[0].text = 'Changed'
        return write_docx_model(model, path)

    monkeypatch.setattr('textalchemy.convert.executor._write_docx', change_text)
    report = ConversionExecutor().execute(ConversionRequest(source, target, DocFormat.MODEL, DocFormat.DOCX,
        emphasis_loss_policy=EmphasisLossPolicy(1000)))
    assert not report.success and not target.exists()
    assert report.metrics['emphasis_quality_gate']['changed_characters'] is None


def test_emphasis_inventory_is_bounded(monkeypatch):
    monkeypatch.setattr('textalchemy.core.emphasis_quality.MAX_EMPHASIS_RUNS', 2)
    inventory = EmphasisInventory()
    for bold in (True, False, True):
        inventory.add(TextRun('x', TextStyle(bold=bold)))
    assert inventory.to_dict()['runs'] is None
    assert inventory.to_dict()['characters'] == 3


def test_cli_emphasis_budget(tmp_path, capsys):
    import json

    from textalchemy.__main__ import main

    source, target = tmp_path / 'source.docx', tmp_path / 'result.txt'
    write_docx_model(emphasis_document(), source)
    assert main(['convert-file', str(source), str(target), '--max-changed-emphasis', '0', '--json']) == 1
    data = json.loads(capsys.readouterr().out)
    assert data['metrics']['emphasis_quality_gate']['changed_characters'] == 4
    assert not target.exists()
