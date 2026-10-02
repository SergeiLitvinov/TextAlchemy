"""Formula content budgets inspect real serialized output before publication."""

import json

import pytest

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.document_codec import save_document
from textalchemy.core.document_model import DocumentModel, Formula, FormulaFormat, Paragraph, Section, TextRun
from textalchemy.core.formula_quality_policy import FormulaLossPolicy, formula_fingerprint
from textalchemy.core.types import DocFormat

MATH = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mfrac><mi>x</mi><mn>2</mn></mfrac></math>'


def source_document(tmp_path, count=1):
    source = tmp_path / 'source.json'
    save_document(DocumentModel(sections=[Section(blocks=[
        Paragraph(content=[TextRun('Формула: '), *[Formula(MATH, FormulaFormat.MATHML) for _ in range(count)]]),
    ])]), source)
    return source


@pytest.mark.parametrize('limit', [-1, True, 0.2, '0'])
def test_invalid_formula_budget(limit):
    with pytest.raises(ValueError):
        FormulaLossPolicy(limit)


def test_mathml_to_native_docx_matches_and_counts_repeats(tmp_path):
    source = source_document(tmp_path, count=2)
    output = tmp_path / 'result.docx'
    report = ConversionExecutor().execute(ConversionRequest(
        source, output, DocFormat.MODEL, DocFormat.DOCX, formula_loss_policy=FormulaLossPolicy(0),
    ))
    assert report.success, report.to_dict()
    gate = report.metrics['formula_quality_gate']
    assert gate['source_formulas'] == 2 and gate['changed_formulas'] == 0 and gate['verified']
    from textalchemy.formats.docx import read_docx_model

    assert sum(isinstance(item, Formula) for item in read_docx_model(output).sections[0].blocks[0].content) == 2


def test_native_docx_formulas_survive_two_model_cycles(tmp_path):
    source = source_document(tmp_path, count=2)
    native = tmp_path / 'native.docx'
    executor = ConversionExecutor()
    assert executor.execute(ConversionRequest(source, native, DocFormat.MODEL, DocFormat.DOCX)).success
    for cycle in range(2):
        model, result = tmp_path / f'model-{cycle}.json', tmp_path / f'result-{cycle}.docx'
        for before, after, source_format, target_format in (
            (native, model, DocFormat.DOCX, DocFormat.MODEL),
            (model, result, DocFormat.MODEL, DocFormat.DOCX),
        ):
            report = executor.execute(ConversionRequest(
                before, after, source_format, target_format, formula_loss_policy=FormulaLossPolicy(0),
            ))
            assert report.success, report.to_dict()
            assert report.metrics['formula_quality_gate']['source_formulas'] == 2
            assert report.metrics['formula_quality_gate']['changed_formulas'] == 0
        native = result


@pytest.mark.parametrize('limit, accepted', [(0, False), (1, True)])
@pytest.mark.parametrize('change', ['replace', 'remove'])
def test_formula_change_is_blocked_independently_of_object_presence(tmp_path, monkeypatch, limit, accepted, change):
    from textalchemy.convert.docx_writer import write_docx_model

    source = source_document(tmp_path, count=2)
    output = tmp_path / 'result.docx'
    output.write_bytes(b'previous result')

    def corrupt_formula(model, path):
        content = model.sections[0].blocks[0].content
        if change == 'remove':
            content.pop()
        else:
            content[-1].value = MATH.replace('<mn>2</mn>', '<mn>3</mn>')
        return write_docx_model(model, path)

    monkeypatch.setattr('textalchemy.convert.executor._write_docx', corrupt_formula)
    report = ConversionExecutor().execute(ConversionRequest(
        source, output, DocFormat.MODEL, DocFormat.DOCX, formula_loss_policy=FormulaLossPolicy(limit),
    ))
    assert report.success is accepted, report.to_dict()
    assert report.metrics['formula_quality_gate']['changed_formulas'] == 1
    assert (output.read_bytes() != b'previous result') is accepted
    assert not list(tmp_path.glob('.textalchemy-*'))


def test_unsupported_formula_cannot_pass_even_permissive_budget(tmp_path):
    source = tmp_path / 'unsupported.json'
    save_document(DocumentModel(sections=[Section(blocks=[Formula(
        '<math><unknown>x</unknown></math>', FormulaFormat.MATHML,
    )])]), source)
    output = tmp_path / 'result.docx'
    report = ConversionExecutor().execute(ConversionRequest(
        source, output, DocFormat.MODEL, DocFormat.DOCX, formula_loss_policy=FormulaLossPolicy(100),
    ))
    gate = report.metrics['formula_quality_gate']
    assert not report.success and not output.exists()
    assert gate['changed_formulas'] is None and gate['reason'] == 'unavailable'


def test_xml_prefixes_and_indentation_are_ignored_but_symbols_are_not():
    namespace = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
    first = Formula(f'<m:oMath xmlns:m="{namespace}"><m:r><m:t>x</m:t></m:r></m:oMath>', FormulaFormat.OMML)
    second = Formula(f'<q:oMath xmlns:q="{namespace}">\n <q:r><q:t>x</q:t></q:r>\n</q:oMath>', FormulaFormat.OMML)
    assert formula_fingerprint(first) == formula_fingerprint(second)
    second.value = second.value.replace('>x<', '>y<')
    assert formula_fingerprint(first) != formula_fingerprint(second)
    assert formula_fingerprint(Formula('<broken', FormulaFormat.OMML)) is None


def test_cli_formula_budget_is_independent_of_text_budget(tmp_path, capsys):
    from textalchemy.__main__ import main

    source = source_document(tmp_path)
    assert main(['convert-file', str(source), str(tmp_path / 'result.docx'),
                 '--max-changed-formulas', '0', '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['metrics']['formula_quality_gate']['accepted']
    assert 'text_quality_gate' not in report['metrics']
