"""Plain-text round-trip and explicit rich-content losses."""

import pytest

from textalchemy.convert import ConversionExecutor, ConversionRequest, write_txt_model
from textalchemy.core.document_codec import save_document
from textalchemy.core.document_model import (
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    Paragraph,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
)
from textalchemy.core.types import DocFormat
from textalchemy.formats.txt import read_txt_model


@pytest.mark.parametrize("text", ["", "\n", "Привет\n\nМир\n", "  пробелы\tзначение  ", "😀\n日本語"])
def test_txt_model_mutation_twice(tmp_path, text):
    source = tmp_path / "source.txt"
    source.write_bytes(text.encode("utf-8"))
    model = read_txt_model(source)
    model.sections[0].blocks[0].content[0].text += "!"
    expected = text.split("\n")
    expected[0] += "!"
    for _ in range(2):
        saved, output = tmp_path / "model.json", tmp_path / "result.txt"
        save_document(model, saved)
        report = ConversionExecutor().execute(ConversionRequest(saved, output, DocFormat.MODEL, DocFormat.TXT))
        assert report.success, report.to_dict()
        assert output.read_bytes() == "\n".join(expected).encode("utf-8")
        model = read_txt_model(output)


def test_rich_content_is_flattened_with_losses(tmp_path):
    document = DocumentModel(
        sections=[
            Section(
                blocks=[
                    Paragraph(
                        [
                            TextRun("Label", link="https://example.com"),
                            Formula("x^2", FormulaFormat.LATEX),
                            Image("missing", alt_text="Diagram"),
                        ]
                    ),
                    Table([TableRow([TableCell([Paragraph([TextRun("A")])]), TableCell([Paragraph([TextRun("B")])])])]),
                ]
            )
        ]
    )
    output = tmp_path / "rich.txt"
    report = write_txt_model(document, output)
    assert report.success and not report.lossless
    assert output.read_bytes() == b"Labelx^2Diagram\nA\tB"
    assert {"hyperlinks", "formulas", "images", "tables"} <= {issue.feature for issue in report.issues}


def test_write_error_preserves_existing_target(tmp_path, monkeypatch):
    output = tmp_path / "existing.txt"
    output.write_bytes(b"original")

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr("textalchemy.convert.txt_writer.atomic_write_bytes", fail)
    report = write_txt_model(DocumentModel(), output)
    assert not report.success
    assert output.read_bytes() == b"original"


def test_cli_pipeline_and_web_catalog(tmp_path, capsys):
    import json

    from textalchemy.__main__ import main
    from textalchemy.pipeline.render import render_txt_model
    from textalchemy.web.services.conversion_catalog import MEDIA_TYPES, available_conversions

    model = DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("Текст\n")])])])
    source, output = tmp_path / "model.json", tmp_path / "text.txt"
    save_document(model, source)
    assert main(["convert-file", str(source), str(output), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["success"]
    assert render_txt_model(document=model, output_path=output)["success"]
    assert output.read_bytes() == "Текст\n".encode()
    catalog = available_conversions(ConversionExecutor())
    source = next(item for item in catalog["sources"] if item["format"] == "model")
    target = next(item for item in source["targets"] if item["format"] == "txt")
    assert target["extension"] == ".txt" and "faithful" not in target["modes"]
    assert MEDIA_TYPES[DocFormat.TXT].startswith("text/plain")
