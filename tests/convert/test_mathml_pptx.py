"""Структура и изменение нативных формул после повторного экспорта PPTX."""

from __future__ import annotations

from zipfile import ZipFile

import pytest

pytest.importorskip("pptx")
from lxml import etree

from textalchemy.convert.mathml_to_omml import MATHML, OMML, mathml_to_omml
from textalchemy.convert.pptx_to_html._omml import convert_omml
from textalchemy.convert.pptx_writer import write_pptx_model
from textalchemy.core.document_codec import document_from_json, document_to_json
from textalchemy.core.document_model import DocumentModel, Formula, FormulaFormat, Paragraph, Section, TextRun
from textalchemy.formats.pptx import read_pptx_model

CASES = [
    ('<mover accent="true"><mi>x</mi><mo>‾</mo></mover>', "bar"),
    ('<munder accentunder="true"><mi>x</mi><mo>_</mo></munder>', "bar"),
    ('<mover accent="true"><mi>x</mi><mo stretchy="true">⏞</mo></mover>', "groupChr"),
    ('<munder accentunder="true"><mi>x</mi><mo>⏟</mo></munder>', "groupChr"),
    ('<munder accentunder="false"><munder accentunder="true"><mi>x</mi><mo>⏟</mo></munder><mi>n</mi></munder>', "groupChr"),
    ('<munder accentunder="false"><mi>x</mi><mrow><mi>n</mi><mo>→</mo><mn>0</mn></mrow></munder>', "limLow"),
    ('<mover accent="false"><mi>x</mi><mn>2</mn></mover>', "limUpp"),
    ('<munderover accent="false" accentunder="false"><mi>x</mi><mn>1</mn><mn>2</mn></munderover>', "limUpp"),
    ('<mover accent="true"><mi>x</mi><mo>→</mo></mover>', "acc"),
    ('<munderover accent="true" accentunder="false"><mi>x</mi><mn>1</mn><mo>^</mo></munderover>', "acc"),
    ("<mfrac><mi>x</mi><mn>2</mn></mfrac>", "f"),
    ("<msub><mi>x</mi><mn>1</mn></msub>", "sSub"),
    ("<msup><mi>x</mi><mn>2</mn></msup>", "sSup"),
    ("<msubsup><mi>x</mi><mn>1</mn><mn>2</mn></msubsup>", "sSubSup"),
    ("<msqrt><mi>x</mi><mo>+</mo><mn>1</mn></msqrt>", "rad"),
    ("<mroot><mi>x</mi><mn>3</mn></mroot>", "rad"),
    ('<mfenced open="[" close="]"><mi>x</mi><mi>α</mi></mfenced>', "d"),
    (
        "<mtable><mtr><mtd><mi>x</mi></mtd><mtd><mn>2</mn></mtd></mtr>"
        "<mtr><mtd><mn>3</mn></mtd><mtd><mn>4</mn></mtd></mtr></mtable>",
        "m",
    ),
    ('<mstyle mathvariant="bold"><mi>x</mi></mstyle>', "r"),
    ('<semantics><mi>x</mi><annotation encoding="application/x-tex">x</annotation></semantics>', "r"),
]


@pytest.mark.parametrize("body,native_tag", CASES)
@pytest.mark.parametrize("inline", [True, False])
def test_native_formula_mutation(tmp_path, body, native_tag, inline):
    source = f'<math xmlns="{MATHML}">{body}</math>'
    formula = Formula(source, FormulaFormat.MATHML, fallback_text="fallback")
    block = Paragraph(content=[TextRun("Before "), formula, TextRun(" After")]) if inline else formula
    model = DocumentModel(sections=[Section(blocks=[block])])
    for cycle in range(2):
        model = document_from_json(document_to_json(model))
        path = tmp_path / f"formula{cycle}.pptx"
        report = write_pptx_model(model, path)
        assert report.success
        assert not [issue for issue in report.issues if issue.feature == "formulas"]
        with ZipFile(path) as package:
            slide = etree.fromstring(package.read("ppt/slides/slide1.xml"))
        assert slide.find(f".//{{{OMML}}}{native_tag}") is not None
        assert slide.find(f".//{{{OMML}}}oMath").getparent().tag.endswith("}m")
        model = read_pptx_model(path)
        paragraph = model.sections[0].blocks[0]
        restored = next(item for item in paragraph.content if isinstance(item, Formula))
        assert restored.format is FormulaFormat.OMML
        root = etree.fromstring(restored.value.encode())
        tokens = root.findall(f".//{{{OMML}}}t")
        editable = [token for token in tokens if token.text == ("x" if cycle == 0 else "z")]
        assert len(editable) == 1
        editable[0].text = "z"
        restored.value = etree.tostring(root, encoding="unicode")
        if inline:
            assert paragraph.content[0].text == "Before "
            assert paragraph.content[-1].text == " After"
    assert formula.value == source
    assert formula.format is FormulaFormat.MATHML


@pytest.mark.parametrize(
    "body",
    [
        "<mfrac><mi>x</mi></mfrac>",
        "<mroot><mi>x</mi></mroot>",
        "<menclose><mi>x</mi></menclose>",
        '<mi mathvariant="double-struck">x</mi>',
        '<mfrac linethickness="0"><mi>x</mi><mn>2</mn></mfrac>',
        '<mi xmlns="urn:foreign">x</mi>',
        "<mtable><mtr><mtd><mi>x</mi></mtd></mtr><mtr/></mtable>",
        "<mrow>unexpected<mi>x</mi></mrow>",
        '<mover accent="true"><mi>x</mi><mo>?</mo></mover>',
        '<munder accentunder="true"><mi>x</mi><mo>^</mo></munder>',
        '<mover accent="yes"><mi>x</mi><mn>1</mn></mover>',
        "<mover><mi>x</mi><mo>^</mo></mover>",
        "<munderover><mi>x</mi><mn>1</mn></munderover>",
        '<mover accent="true"><mi>x</mi><mo mathvariant="bold">^</mo></mover>',
        '<mover accent="true"><mi>x</mi><mo>⏟</mo></mover>',
        '<munder accentunder="true"><mi>x</mi><mo>⏞</mo></munder>',
        '<mover accent="true"><mi>x</mi><mo stretchy="false">‾</mo></mover>',
    ],
)
def test_unsupported_formula_falls_back_whole(tmp_path, body):
    formula = Formula(f"<math>{body}</math>", FormulaFormat.MATHML, fallback_text="Readable fallback")
    model = DocumentModel(sections=[Section(blocks=[formula])])
    path = tmp_path / "fallback.pptx"
    report = write_pptx_model(model, path)
    assert report.success and not report.lossless
    assert any(issue.feature == "formulas" and issue.location for issue in report.issues)
    with ZipFile(path) as package:
        slide = etree.fromstring(package.read("ppt/slides/slide1.xml"))
    assert slide.find(f".//{{{OMML}}}oMath") is None
    assert read_pptx_model(path).sections[0].blocks[0].plain_text == "Readable fallback"


@pytest.mark.parametrize(
    "value",
    [
        '<!DOCTYPE math [<!ENTITY x SYSTEM "file:///missing">]><math><mi>&x;</mi></math>',
        "<math><mi>&alpha;</mi></math>",
        "<math>" + "<mrow>" * 65 + "<mi>x</mi>" + "</mrow>" * 65 + "</math>",
        "<math>" + "<mi>x</mi>" * 4096 + "</math>",
        "<math><mtext>" + "x" * (1024 * 1024) + "</mtext></math>",
    ],
    ids=["dtd", "entity", "depth", "nodes", "bytes"],
)
def test_unsafe_or_excessive_xml_is_rejected(value):
    with pytest.raises(ValueError):
        mathml_to_omml(value)


@pytest.mark.parametrize(
    "body,tag,children",
    [
        ("<msqrt><mi>x</mi></msqrt>", "msqrt", ["x"]),
        ("<mroot><mi>x</mi><mn>3</mn></mroot>", "mroot", ["x", "3"]),
    ],
)
def test_preview_root_order_and_namespace(body, tag, children):
    root = etree.fromstring(convert_omml(mathml_to_omml(f"<math>{body}</math>")).encode())
    radical = root.find(f".//{{{MATHML}}}{tag}")
    assert radical is not None
    assert ["".join(child.itertext()) for child in radical] == children


def test_preview_matrix_delimiters_and_style():
    value = (
        '<math><mfenced open="[" close="]"><mtable>'
        '<mtr><mtd><mi mathvariant="bold">x</mi></mtd><mtd><mn>2</mn></mtd></mtr>'
        "</mtable></mfenced></math>"
    )
    root = etree.fromstring(convert_omml(mathml_to_omml(value)).encode())
    ns = {"m": MATHML}
    assert root.xpath(".//m:mo/text()", namespaces=ns) == ["[", "]"]
    assert root.xpath("count(.//m:mtable/m:mtr/m:mtd)", namespaces=ns) == 2
    assert root.xpath(".//m:mi/@mathvariant", namespaces=ns) == ["bold"]


def test_fenced_repeats_last_separator_and_preserves_unicode():
    value = '<math><mfenced separators=";,"><mi>α</mi><mi>β</mi><mi>γ</mi><mi>δ</mi></mfenced></math>'
    root = etree.fromstring(mathml_to_omml(value).encode())
    assert root.xpath(".//m:t/text()", namespaces={"m": OMML}) == ["α", ";", "β", ",", "γ", ",", "δ"]


@pytest.mark.parametrize("tag,attribute,native", [("munder", "accentunder", "limLow"), ("mover", "accent", "limUpp")])
def test_limit_direction_survives_preview(tag, attribute, native):
    value = f'<math><{tag} {attribute}="false"><mi>x</mi><mn>7</mn></{tag}></math>'
    omml = mathml_to_omml(value)
    assert etree.fromstring(omml.encode())[0].tag == f"{{{OMML}}}{native}"
    preview = convert_omml(omml)
    root = etree.fromstring(preview.encode())
    limit = root.find(f"{{{MATHML}}}{tag}")
    assert limit is not None and limit.get(attribute) == "false"
    assert ["".join(child.itertext()) for child in limit] == ["x", "7"]
    assert etree.fromstring(mathml_to_omml(preview).encode())[0].tag == f"{{{OMML}}}{native}"


def test_combined_limits_keep_independent_arguments():
    value = "<math><munderover><mi>x</mi><mn>7</mn><mn>9</mn></munderover></math>"
    for _ in range(2):
        native = etree.fromstring(mathml_to_omml(value).encode())
        ns = {"m": OMML}
        assert native.xpath("m:limUpp/m:lim/m:r/m:t/text()", namespaces=ns) == ["9"]
        assert native.xpath("m:limUpp/m:e/m:limLow/m:lim/m:r/m:t/text()", namespaces=ns) == ["7"]
        value = convert_omml(native)
        preview = etree.fromstring(value.encode())
        ns = {"m": MATHML}
        assert preview.xpath("m:mover/m:mn/text()", namespaces=ns) == ["9"]
        assert preview.xpath("m:mover/m:munder/m:mn/text()", namespaces=ns) == ["7"]


@pytest.mark.parametrize(
    "symbol,canonical", [("^", "\u0302"), ("~", "\u0303"), ("→", "\u20d7"), ("˙", "\u0307"), ("¨", "\u0308")]
)
def test_accent_preview_and_edit(tmp_path, symbol, canonical):
    value = f'<math><mover accent="true"><mi>x</mi><mo>{symbol}</mo></mover></math>'
    model = DocumentModel(sections=[Section(blocks=[Formula(value, FormulaFormat.MATHML)])])
    for cycle in range(2):
        model = document_from_json(document_to_json(model))
        path = tmp_path / f"accent{cycle}.pptx"
        assert write_pptx_model(model, path).success
        model = read_pptx_model(path)
        formula = next(item for item in model.sections[0].blocks[0].content if isinstance(item, Formula))
        root = etree.fromstring(formula.value.encode())
        character = root.find(f".//{{{OMML}}}accPr/{{{OMML}}}chr")
        assert character.get(f"{{{OMML}}}val") == (canonical if cycle == 0 else "\u0308")
        preview = etree.fromstring(convert_omml(root).encode())
        assert preview.find(f"{{{MATHML}}}mover").get("accent") == "true"
        assert preview.find(f".//{{{MATHML}}}mo").text == (canonical if cycle == 0 else "\u0308")
        assert "accPr" in mathml_to_omml(etree.tostring(preview, encoding="unicode"))
        character.set(f"{{{OMML}}}val", "\u0308")
        formula.value = etree.tostring(root, encoding="unicode")
