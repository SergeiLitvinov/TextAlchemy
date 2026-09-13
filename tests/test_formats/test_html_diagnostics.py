from pathlib import Path

import pytest

pytest.importorskip("bs4")
pytest.importorskip("tinycss2")

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.document_codec import document_from_json, document_to_json, load_document
from textalchemy.core.types import DocFormat
from textalchemy.formats.html import read_html_model

CORPUS = Path(__file__).parents[1] / "corpus/html-warnings.html"


def test_warning_locations_survive_json_and_report(tmp_path):
    output = tmp_path / "model.json"
    report = ConversionExecutor().execute(ConversionRequest(CORPUS, output, DocFormat.HTML, DocFormat.MODEL))
    assert report.success
    model = document_from_json(document_to_json(load_document(output)))
    diagnostics = model.metadata["html"]
    blocks = {block.properties["html"]["block_id"]: block for block in model.sections[0].blocks}
    css = next(w for w in diagnostics["warnings"] if "background-color" in w["message"])
    resource = next(w for w in diagnostics["warnings"] if w["feature"] == "html-resource")
    assert blocks[css["location"]].plain_text == "Абзац с неподдержанным фоном."
    assert "Результат измерения:" in blocks[resource["location"]].plain_text
    assert diagnostics["locations"][resource["location"]]["images"] == [
        {"alt": "График измерений", "source": "missing-chart.png"}
    ]
    general = next(w for w in diagnostics["warnings"] if w["message"].endswith("page"))
    assert general["location"] == "html:document"
    assert diagnostics["locations"][general["location"]]["label"] == "Весь документ"
    serialized = report.to_dict()
    assert {i["location"] for i in serialized["issues"]} == {w["location"] for w in diagnostics["warnings"]}
    assert serialized["metrics"]["step_metrics"]["html.model"]["html_locations"] == diagnostics["locations"]
    copied = tmp_path / "renamed.html"
    copied.write_bytes(CORPUS.read_bytes())
    assert read_html_model(copied).metadata["html"] == diagnostics


def test_repeated_inline_and_nested_warnings_point_to_separate_blocks(tmp_path):
    source = tmp_path / "nested.html"
    source.write_text(
        '<div>Начало<p>Без проблем</p><span style="position:absolute">Хвост</span></div>'
        '<table><tr><td><p id="same" style="position:absolute">Ячейка</p></td></tr></table>'
        '<p id="same"><img src="missing.png"></p><p><img src="missing.png"></p>', encoding="utf-8",
    )
    model = document_from_json(document_to_json(read_html_model(source)))
    diagnostics = model.metadata["html"]
    css = [w for w in diagnostics["warnings"] if w["feature"] == "html-css"]
    assert len(css) == 2
    assert {diagnostics["locations"][w["location"]]["text"] for w in css} == {"Хвост", "Ячейка"}
    resources = [w for w in diagnostics["warnings"] if w["feature"] == "html-resource"]
    assert len(resources) == 2
    assert len({w["location"] for w in resources}) == 2
    for warning, block in zip(resources, model.sections[0].blocks[-2:], strict=True):
        assert warning["location"] == block.properties["html"]["block_id"]
        assert block.plain_text == ""
        assert diagnostics["locations"][warning["location"]]["images"][0]["source"] == "missing.png"
