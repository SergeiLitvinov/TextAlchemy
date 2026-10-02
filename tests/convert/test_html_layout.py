"""Стадия HTML layout готовит снимок геометрии, не меняя источник."""

from copy import deepcopy

import pytest

from textalchemy.convert.html_layout import HtmlLayoutStage
from textalchemy.convert.html_writer import write_html_model
from textalchemy.convert.stages import StageContext
from textalchemy.core.document_codec import document_to_dict
from textalchemy.core.document_model import (
    Box,
    DocumentModel,
    Image,
    Paragraph,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
)


def test_layout_recurses_and_preserves_source_and_inline_flow(tmp_path):
    inline = Image("inline", box=Box(0, 0, 12, 6))
    paragraph = Paragraph([TextRun("Before"), inline], properties={"html_layout": {"styles": ["stale"]}})
    table = Table([TableRow([TableCell([paragraph])])], box=Box(0, 0, 120, 30))
    document = DocumentModel(sections=[Section(blocks=[table], headers=[Paragraph([TextRun("Header")])])])
    before = deepcopy(document_to_dict(document))
    result = HtmlLayoutStage().execute(document, StageContext(tmp_path / "out.html"))
    assert result.report.success
    prepared_table = result.value.sections[0].blocks[0]
    prepared_paragraph = prepared_table.rows[0].cells[0].blocks[0]
    assert "position:absolute" in prepared_table.properties["html_layout"]["styles"]
    assert prepared_paragraph.properties["html_layout"]["styles"] == []
    assert prepared_paragraph.content[1].properties["html_layout"]["styles"] == ["width:12pt", "height:6pt"]
    assert result.report.metrics["html_layout"] == {
        "stage": "html.layout",
        "positioned_blocks": 1,
        "origin_blocks": 1,
        "affine_objects": 0,
        "inline_images": 1,
    }
    assert document_to_dict(document) == before


def test_layout_converts_affine_translation_but_preserves_model_points(tmp_path):
    paragraph = Paragraph(
        [TextRun("Transformed")],
        box=Box(0, 0, 72, 36),
        properties={
            "pptx": {"transform": {"matrix": [-1, 0, 0, 1, 72, 36], "width_pt": 72, "height_pt": 36}},
        },
    )
    document = DocumentModel(sections=[Section(blocks=[paragraph])])
    result = HtmlLayoutStage().execute(document, StageContext(tmp_path / "out.html"))
    prepared = result.value.sections[0].blocks[0]
    assert "transform:matrix(-1,0,0,1,96,48)" in prepared.properties["html_layout"]["styles"]
    assert prepared.properties["pptx"]["transform"]["matrix"] == [-1, 0, 0, 1, 72, 36]
    assert "html_layout" not in paragraph.properties


@pytest.mark.parametrize("existing", [False, True])
def test_cancelled_layout_preserves_output(tmp_path, monkeypatch, existing):
    execute = HtmlLayoutStage.execute

    def cancel(self, value, context):
        return execute(self, value, StageContext(context.output_path, cancelled=lambda: True))

    monkeypatch.setattr(HtmlLayoutStage, "execute", cancel)
    output = tmp_path / "result.html"
    if existing:
        output.write_bytes(b"previous")
    report = write_html_model(DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("New")])])]), output)
    assert not report.success
    assert any(issue.feature == "cancelled" for issue in report.issues)
    if existing:
        assert output.read_bytes() == b"previous"
    else:
        assert not output.exists()
