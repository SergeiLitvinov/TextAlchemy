"""Tests for target-specific font subsetting and DOCX embedding."""

import zipfile
from uuid import UUID

from docx import Document

from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import DocumentModel, Paragraph, Section, TextRun, TextStyle
from textalchemy.fonts.docx_embedding import _obfuscate, embed_docx_fonts, verify_docx_font_embedding
from textalchemy.fonts.embedding import FontUsage, collect_font_usages, subset_font


def _resolved_style(path, *, family="Demo Sans", bold=False):
    return TextStyle(
        font_family=family,
        bold=bold,
        properties={
            "font_resolution": {
                "resolved": family,
                "path": str(path),
                "embeddable": True,
                "subsettable": True,
            }
        },
    )


def test_collect_font_usages_accumulates_characters_by_face(tmp_path):
    path = tmp_path / "demo.ttf"
    path.write_bytes(b"font")
    document = DocumentModel(
        sections=[
            Section(
                blocks=[Paragraph(content=[TextRun("aba", _resolved_style(path)), TextRun("c", _resolved_style(path))])]
            )
        ]
    )

    usages = collect_font_usages(document)

    assert len(usages) == 1
    assert usages[0].characters == frozenset("abc")


def test_docx_embedding_writes_obfuscated_part_and_font_table(tmp_path, monkeypatch):
    font_path = tmp_path / "demo.ttf"
    font_path.write_bytes(bytes(range(64)))
    model = DocumentModel(
        sections=[Section(blocks=[Paragraph(content=[TextRun("abc", _resolved_style(font_path))])])]
    )
    target = Document()
    report = ConversionReport(tmp_path / "embedded.docx")
    monkeypatch.setattr("textalchemy.fonts.docx_embedding.subset_font", lambda _usage: b"subset-font-data" * 3)

    embed_docx_fonts(target, model, report)
    target.save(report.output_path)
    verify_docx_font_embedding(report.output_path, report)

    with zipfile.ZipFile(report.output_path) as package:
        names = package.namelist()
        font_name = next(name for name in names if name.startswith("word/fonts/") and name.endswith(".odttf"))
        font_table = package.read("word/fontTable.xml").decode("utf-8")
        relationships = package.read("word/_rels/fontTable.xml.rels").decode("utf-8")
        embedded = package.read(font_name)
    assert "embedRegular" in font_table and "fontKey" in font_table
    assert "relationships/font" in relationships
    assert embedded != b"subset-font-data" * 3
    assert report.metrics["font_embedding"]["embedded_faces"] == 1
    assert report.metrics["font_embedding"]["subset_bytes"] == len(b"subset-font-data" * 3)
    assert report.metrics["font_embedding"]["verified_faces"] == 1


def test_docx_obfuscation_is_reversible():
    key = UUID("00112233-4455-6677-8899-aabbccddeeff")
    source = bytes(range(64))

    assert _obfuscate(_obfuscate(source, key), key) == source


def test_subset_font_honors_no_subsetting_license(tmp_path):
    path = tmp_path / "licensed.ttf"
    path.write_bytes(b"full-font-program")
    usage = FontUsage("Licensed", path, False, False, frozenset("abc"), True, False)

    assert subset_font(usage) == b"full-font-program"
