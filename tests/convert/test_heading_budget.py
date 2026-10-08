"""Heading roles are measured by the library and bounded before publication."""

import json
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from opendoc_model import DocumentModel, Heading, Paragraph, Section, TextRun, TextStyle, save_document, set_heading

from textalchemy.__main__ import main
from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.convert.heading_budget import HeadingBudget
from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.inspection import compare_inspections, inspect_document_model
from textalchemy.core.types import DocFormat


def heading_model() -> DocumentModel:
    heading = Paragraph(content=[TextRun('Unique heading')])
    set_heading(heading, Heading(2))
    return DocumentModel(sections=[Section(blocks=[heading, Paragraph(content=[TextRun('Body')])])])


@pytest.mark.parametrize('limit,accepted', [(0, False), (1, True)])
def test_real_txt_heading_loss_and_repeated_publication(tmp_path: Path, limit: int, accepted: bool):
    source = save_document(heading_model(), tmp_path / 'source.json')
    original = source.read_bytes()
    output = tmp_path / 'result.txt'
    output.write_bytes(b'Previous result')
    for _ in range(2):
        report = ConversionExecutor().execute(ConversionRequest(
            source, output, DocFormat.MODEL, DocFormat.TXT, heading_loss_policy=HeadingBudget(limit)))
        assert report.success is accepted, report.to_dict()
        gate = report.metrics['heading_quality_gate']
        assert gate['changed_headings'] == 1 and gate['unmatched_source_headings'] == 0
        assert gate['verified'] and gate['accepted'] is accepted
        assert gate['visual_score'] is None
        if accepted:
            assert output.read_text(encoding='utf-8') == 'Unique heading\nBody'
        else:
            assert output.read_bytes() == b'Previous result'
        assert not list(tmp_path.glob('.textalchemy-*'))
    assert source.read_bytes() == original


def _check_docx_heading_cycles(source, output):
    from opendoc_model import get_heading, load_document

    original = source.read_bytes()
    current = source
    executor = ConversionExecutor()
    for cycle in (1, 2):
        report = executor.execute(ConversionRequest(
            current, output, DocFormat.MODEL, DocFormat.DOCX, heading_loss_policy=HeadingBudget(0)))
        assert report.success, report.to_dict()
        gate = report.metrics['heading_quality_gate']
        assert gate['changed_headings'] == 0 and gate['verified'] and gate['accepted']
        snapshot = source.parent / f'cycle-{cycle}.json'
        imported = executor.execute(ConversionRequest(output, snapshot, DocFormat.DOCX, DocFormat.MODEL))
        assert imported.success, imported.to_dict()
        model = load_document(snapshot)
        assert get_heading(model.sections[0].blocks[0]).level == 2
        assert get_heading(model.sections[0].blocks[1]) is None
        current = snapshot
    assert source.read_bytes() == original


def test_docx_without_named_style_preserves_semantic_heading(tmp_path):
    source = save_document(heading_model(), tmp_path / 'source.json')
    _check_docx_heading_cycles(source, tmp_path / 'result.docx')


def test_docx_named_style_is_native_and_reimport_preserves_model_role(tmp_path):
    model = heading_model()
    model.styles['Heading 2'] = TextStyle(properties={'style_name': 'Heading 2', 'style_type': 'paragraph'})
    model.sections[0].blocks[0].style_id = 'Heading 2'
    source = save_document(model, tmp_path / 'source.json')
    output = tmp_path / 'result.docx'
    baseline = ConversionExecutor().execute(ConversionRequest(source, output, DocFormat.MODEL, DocFormat.DOCX))
    assert baseline.success and not baseline.issues
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with ZipFile(output) as package:
        document = ElementTree.fromstring(package.read('word/document.xml'))
        styles = ElementTree.fromstring(package.read('word/styles.xml'))
    assert document.find('.//w:pStyle', ns).get(f"{{{ns['w']}}}val") == 'Heading2'
    assert styles.find('.//w:style[@w:styleId="Heading2"]/w:pPr/w:outlineLvl', ns).get(f"{{{ns['w']}}}val") == '1'
    _check_docx_heading_cycles(source, output)


def test_model_roundtrip_preserves_heading_role(tmp_path):
    source = save_document(heading_model(), tmp_path / 'source.json')
    output = tmp_path / 'result.json'
    report = ConversionExecutor().execute(ConversionRequest(
        source, output, DocFormat.MODEL, DocFormat.MODEL, heading_loss_policy=HeadingBudget(0)))
    assert report.success, report.to_dict()
    assert report.metrics['heading_quality_gate']['changed_headings'] == 0


def test_missing_source_heading_counts_even_without_a_match(tmp_path):
    source = heading_model()
    target = DocumentModel(sections=[Section(blocks=[source.sections[0].blocks[1]])])
    comparison = compare_inspections(inspect_document_model(source), inspect_document_model(target))
    report = ConversionReport(tmp_path / 'result.json')
    assert not HeadingBudget(0).evaluate(report, comparison)
    assert report.metrics['heading_quality_gate']['changed_headings'] == 1
    assert report.metrics['heading_quality_gate']['unmatched_source_headings'] == 1


@pytest.mark.parametrize('unknown', ['heading-coverage', 'heuristic', 'ambiguous', 'count', 'scope'])
def test_unknown_or_uncertain_measurement_is_not_zero(tmp_path, unknown):
    model = heading_model()
    comparison = compare_inspections(inspect_document_model(model), inspect_document_model(model))
    if unknown == 'heading-coverage':
        comparison.object_diff['headings_available'] = False
    elif unknown in {'heuristic', 'ambiguous'}:
        comparison.object_diff['matching'][unknown] = 1
    elif unknown == 'count':
        comparison.object_diff['changed_headings'] = None
    else:
        comparison.target.metadata.pop('object_inventory_scope')
    report = ConversionReport(tmp_path / 'result.json')
    assert not HeadingBudget(100).evaluate(report, comparison)
    gate = report.metrics['heading_quality_gate']
    assert gate['changed_headings'] is None and not gate['verified']


@pytest.mark.parametrize('invalid', [-1, True, 0.5])
def test_invalid_budget(invalid):
    with pytest.raises(ValueError):
        HeadingBudget(invalid)


def test_cli_zero_heading_budget_preserves_previous_result(tmp_path, capsys):
    source = save_document(heading_model(), tmp_path / 'source.json')
    output = tmp_path / 'result.txt'
    output.write_bytes(b'Previous result')
    assert main(['convert-file', str(source), str(output), '--max-changed-headings', '0', '--json']) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['metrics']['heading_quality_gate']['changed_headings'] == 1
    assert output.read_bytes() == b'Previous result'
