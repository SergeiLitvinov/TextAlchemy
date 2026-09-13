"""Повторное сохранение черт и группирующих скобок с изменением положения."""

from __future__ import annotations

import pytest

pytest.importorskip("pptx")
from lxml import etree

from textalchemy.convert.mathml_to_omml import MATHML, OMML, mathml_to_omml
from textalchemy.convert.pptx_to_html._omml import convert_omml
from textalchemy.convert.pptx_writer import write_pptx_model
from textalchemy.core.document_codec import document_from_json, document_to_json
from textalchemy.core.document_model import DocumentModel, Formula, FormulaFormat, Section
from textalchemy.formats.pptx import read_pptx_model


@pytest.mark.parametrize("native,above", [("bar", True), ("bar", False), ("groupChr", True), ("groupChr", False)])
def test_decoration_position_mutation(tmp_path, native, above):
    symbol = ("⏞" if above else "⏟") if native == "groupChr" else ("‾" if above else "_")
    tag, attribute = ("mover", "accent") if above else ("munder", "accentunder")
    inner = f'<{tag} {attribute}="true"><mi>x</mi><mo>{symbol}</mo></{tag}>'
    value = f'<math><{tag} {attribute}="false">{inner}<mi>n</mi></{tag}></math>'
    model = DocumentModel(sections=[Section(blocks=[Formula(value, FormulaFormat.MATHML)])])
    for cycle in range(2):
        model = document_from_json(document_to_json(model))
        path = tmp_path / f"decoration{cycle}.pptx"
        report = write_pptx_model(model, path)
        assert report.success and not any(issue.feature == "formulas" for issue in report.issues)
        model = read_pptx_model(path)
        formula = next(item for item in model.sections[0].blocks[0].content if isinstance(item, Formula))
        root = etree.fromstring(formula.value.encode())
        current_above = above if cycle == 0 else not above
        props = root.find(f".//{{{OMML}}}{native}Pr")
        position = props.find(f"{{{OMML}}}pos")
        assert position.get(f"{{{OMML}}}val") == ("top" if current_above else "bot")
        preview = convert_omml(root)
        rendered = etree.fromstring(preview.encode())
        ns = {"m": MATHML}
        decoration = rendered.xpath('.//m:mover[@accent="true"] | .//m:munder[@accentunder="true"]', namespaces=ns)[0]
        assert decoration.tag == f"{{{MATHML}}}" + ("mover" if current_above else "munder")
        expected = ("⏞" if current_above else "⏟") if native == "groupChr" else ("‾" if current_above else "_")
        assert decoration.find(f"{{{MATHML}}}mo").text == expected
        assert rendered.xpath(".//m:mi/text()", namespaces=ns) == ["x", "n"]
        restored = etree.fromstring(mathml_to_omml(preview).encode())
        assert restored.find(f".//{{{OMML}}}{native}") is not None
        position.set(f"{{{OMML}}}val", "bot" if above else "top")
        if native == "groupChr":
            props.find(f"{{{OMML}}}chr").set(f"{{{OMML}}}val", "⏟" if above else "⏞")
            props.find(f"{{{OMML}}}vertJc").set(f"{{{OMML}}}val", "top" if above else "bot")
        formula.value = etree.tostring(root, encoding="unicode")


@pytest.mark.parametrize("symbol,above", [("¯", True), ("\u0305", True), ("\u0332", False)])
def test_bar_unicode_aliases(symbol, above):
    tag, attribute = ("mover", "accent") if above else ("munder", "accentunder")
    root = etree.fromstring(
        mathml_to_omml(f'<math><{tag} {attribute}="true"><mi>x</mi><mo>{symbol}</mo></{tag}></math>').encode()
    )
    assert root.find(f"{{{OMML}}}bar/{{{OMML}}}barPr/{{{OMML}}}pos").get(f"{{{OMML}}}val") == ("top" if above else "bot")
