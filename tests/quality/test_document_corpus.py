"""Golden- и визуальные smoke-тесты воспроизводимого корпуса."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import fitz
from lxml import etree

from tests.corpus.scientific_report import build_scientific_report, sha256
from textalchemy.convert.docx_writer import write_docx_model
from textalchemy.convert.pdf_writer import write_pdf_model
from textalchemy.core.document_model import Image as ModelImage
from textalchemy.core.document_model import ImageCrop, Paragraph, Table
from textalchemy.core.inspection import compare_inspections, inspect_document_model, inspect_path
from textalchemy.formats.docx import read_docx_model

CORPUS_DIR = Path(__file__).parents[1] / "corpus"
GOLDEN = json.loads((CORPUS_DIR / "scientific_report.golden.json").read_text(encoding="utf-8"))


def test_scientific_report_builder_is_reproducible_and_contains_edge_parts(tmp_path):
    first = build_scientific_report(tmp_path / "first.docx")
    second = build_scientific_report(tmp_path / "second.docx")

    assert sha256(first) == sha256(second)
    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        for name in names:
            if name.endswith((".xml", ".rels")):
                etree.fromstring(archive.read(name))
        document_xml = archive.read("word/document.xml").decode("utf-8")
        numbering_xml = archive.read("word/numbering.xml").decode("utf-8")
        settings_xml = archive.read("word/settings.xml").decode("utf-8")
        styles_xml = archive.read("word/styles.xml").decode("utf-8")
        footnote_relationships = archive.read("word/_rels/footnotes.xml.rels").decode("utf-8")
        endnote_relationships = archive.read("word/_rels/endnotes.xml.rels").decode("utf-8")
        footer_xml = "".join(
            archive.read(name).decode("utf-8")
            for name in names
            if name.startswith("word/footer") and name.endswith(".xml")
        )
        header_xml = "".join(
            archive.read(name).decode("utf-8")
            for name in names
            if name.startswith("word/header") and name.endswith(".xml")
        )
    assert "word/media/vector-curve.svg" in names
    assert "word/footnotes.xml" in names
    assert "word/endnotes.xml" in names
    assert "word/media/footnote-icon.png" in names
    assert "<m:oMath" in document_xml
    assert "footnoteReference" in document_xml
    assert "endnoteReference" in document_xml
    assert "bookmarkStart" in document_xml
    assert 'w:anchor="quality_model"' in document_xml
    assert "NUMPAGES" in footer_xml
    assert "FIRST PAGE" in header_xml
    assert "EVEN PAGE" in header_xml
    assert "ODD PAGE" in header_xml
    assert "<wp:anchor" in document_xml
    assert '<wp:positionH relativeFrom="column"><wp:align>center</wp:align>' in document_xml
    assert '<a:srcRect l="3000" t="2000" r="4000" b="1000"/>' in document_xml
    assert 'rot="180000"' in document_xml
    assert '<wp:wrapTight wrapText="bothSides"><wp:wrapPolygon edited="1">' in document_xml
    assert "abstractNum" in numbering_xml
    assert "evenAndOddHeaders" in settings_xml
    assert "CorpusScientificTable" in styles_xml
    assert "rIdNoteImage" in footnote_relationships
    assert 'TargetMode="External"' in footnote_relationships
    assert 'TargetMode="External"' in endnote_relationships


def test_scientific_report_matches_structural_golden(tmp_path):
    source = build_scientific_report(tmp_path / "scientific-report.docx")
    inspection = inspect_path(source)

    assert inspection.valid
    assert inspection.source_format == GOLDEN["source_format"]
    for name, value in GOLDEN["metadata"].items():
        assert inspection.metadata[name] == value
    for name, value in GOLDEN["metrics"].items():
        assert inspection.metrics[name] == value
    assert inspection.formula_formats == GOLDEN["formula_formats"]
    assert [[page["width_pt"], page["height_pt"]] for page in inspection.pages] == GOLDEN["page_sizes_pt"]
    assert not [issue for issue in inspection.issues if issue.severity.value in {"error", "loss"}]


def test_scientific_report_docx_roundtrip_retains_supported_structure(tmp_path):
    source = build_scientific_report(tmp_path / "source.docx")
    model = read_docx_model(source)
    target = tmp_path / "roundtrip.docx"

    conversion = write_docx_model(model, target)
    restored = read_docx_model(target)
    comparison = compare_inspections(inspect_document_model(model), inspect_document_model(restored))
    assert model.package is not None
    footnote_relationships = {
        item.id: item for item in model.package.relationships if item.source == "/word/footnotes.xml"
    }
    endnote_relationships = {
        item.id: item for item in model.package.relationships if item.source == "/word/endnotes.xml"
    }

    assert conversion.success
    assert footnote_relationships["rIdNoteImage"].target == "/word/media/footnote-icon.png"
    assert footnote_relationships["rIdNoteLink"].target == "https://example.com/conversion-contract"
    assert endnote_relationships["rIdEndnoteLink"].target == "https://example.com/endnote-target"
    assert model.sections[0].first_page_headers[0].plain_text.endswith("FIRST PAGE")
    assert model.sections[0].even_page_headers[0].plain_text.endswith("EVEN PAGE")
    assert model.sections[0].headers[0].plain_text.endswith("ODD PAGE")
    assert restored.sections[0].first_page_headers[0].plain_text.endswith("FIRST PAGE")
    assert restored.sections[0].even_page_headers[0].plain_text.endswith("EVEN PAGE")
    assert restored.sections[0].headers[0].plain_text.endswith("ODD PAGE")
    assert restored.sections[1].properties["different_first_page_header_footer"] is False
    source_table = next(block for block in model.sections[0].blocks if isinstance(block, Table))
    restored_table = next(block for block in restored.sections[0].blocks if isinstance(block, Table))
    assert source_table.style_id == "CorpusScientificTable"
    assert restored_table.style_id == "CorpusScientificTable"
    assert model.styles["__doc_defaults__"].properties["style_type"] == "document-default"
    assert model.styles["__doc_defaults__"].font_family
    assert restored.styles["__doc_defaults__"].font_family == model.styles["__doc_defaults__"].font_family
    source_images = [
        item
        for section in model.sections
        for block in section.blocks
        if isinstance(block, Paragraph)
        for item in block.content
        if isinstance(item, ModelImage)
    ]
    restored_images = [
        item
        for section in restored.sections
        for block in section.blocks
        if isinstance(block, Paragraph)
        for item in block.content
        if isinstance(item, ModelImage)
    ]
    cropped = next(image for image in source_images if image.crop is not None)
    restored_cropped = next(image for image in restored_images if image.crop is not None)
    assert cropped.crop == ImageCrop(left=0.03, top=0.02, right=0.04, bottom=0.01)
    assert restored_cropped.crop == cropped.crop
    assert cropped.box and cropped.box.rotation == 3
    assert restored_cropped.box and restored_cropped.box.rotation == 3
    wrapped = next(image for image in source_images if image.properties.get("wrap_polygon"))
    restored_wrapped = next(image for image in restored_images if image.properties.get("wrap_polygon"))
    assert restored_wrapped.properties["wrap"] == "tight"
    assert restored_wrapped.properties["wrap_text"] == "bothSides"
    assert restored_wrapped.properties["wrap_polygon"] == wrapped.properties["wrap_polygon"]
    source_numbered = [
        block
        for block in model.sections[0].blocks
        if getattr(block, "properties", {}).get("numbering_source") == "style"
    ]
    restored_numbered = [
        block
        for block in restored.sections[0].blocks
        if getattr(block, "properties", {}).get("numbering_source") == "style"
    ]
    assert len(source_numbered) == 3
    assert len(restored_numbered) == 3
    with zipfile.ZipFile(target) as archive:
        target_document = etree.fromstring(archive.read("word/document.xml"))
    namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    list_paragraphs = target_document.xpath(
        ".//w:p[w:pPr/w:pStyle[@w:val='ListNumber']]",
        namespaces=namespaces,
    )
    assert len(list_paragraphs) == 3
    assert not any(paragraph.xpath("./w:pPr/w:numPr", namespaces=namespaces) for paragraph in list_paragraphs)
    with zipfile.ZipFile(target) as archive:
        restored_footnote_relationships = archive.read("word/_rels/footnotes.xml.rels").decode("utf-8")
        restored_endnote_relationships = archive.read("word/_rels/endnotes.xml.rels").decode("utf-8")
    assert "rIdNoteImage" in restored_footnote_relationships
    assert "https://example.com/conversion-contract" in restored_footnote_relationships
    assert "https://example.com/endnote-target" in restored_endnote_relationships
    for metric in (
        "characters",
        "images",
        "cropped_images",
        "rotated_images",
        "floating_images",
        "wrap_polygon_images",
        "tables",
        "formulas",
        "hyperlinks",
        "internal_hyperlinks",
        "bookmark_starts",
        "bookmark_ends",
        "footnote_references",
        "endnote_references",
        "fields",
        "complex_fields",
        "numbered_paragraphs",
        "resources",
        "package_parts",
    ):
        assert comparison.retention[metric]["ratio"] == 1.0
    assert comparison.matching_resource_hashes == 2
    assert comparison.matching_package_part_hashes == 6
    assert comparison.resource_comparison["exact_hash_retention_ratio"] == 1
    assert comparison.resource_comparison["exact_byte_retention_ratio"] == 1
    assert comparison.package_comparison["exact_hash_retention_ratio"] == 1
    assert comparison.package_comparison["exact_byte_retention_ratio"] == 1
    assert comparison.geometry_summary["max_dimension_error_pt"] == 0
    assert comparison.geometry_summary["max_margin_error_pt"] == 0
    assert all(item["same_geometry"] for item in comparison.page_geometry)


def test_scientific_report_pdf_pages_pass_visual_smoke_bounds(tmp_path):
    source = build_scientific_report(tmp_path / "source.docx")
    pdf = tmp_path / "rendered.pdf"
    report = write_pdf_model(read_docx_model(source), pdf)
    bounds = GOLDEN["visual"]

    assert report.success
    with fitz.open(pdf) as rendered:
        assert rendered.page_count >= bounds["minimum_pages"]
        for page in rendered:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1, 1), colorspace=fitz.csGRAY, alpha=False)
            samples = memoryview(pixmap.samples)
            dark = [index for index, value in enumerate(samples) if value < 245]
            assert dark
            ink_ratio = len(dark) / len(samples)
            xs = [index % pixmap.width for index in dark]
            ys = [index // pixmap.width for index in dark]
            width_ratio = (max(xs) - min(xs) + 1) / pixmap.width
            height_ratio = (max(ys) - min(ys) + 1) / pixmap.height
            assert bounds["minimum_ink_ratio"] <= ink_ratio <= bounds["maximum_ink_ratio"]
            assert width_ratio >= bounds["minimum_content_width_ratio"]
            assert height_ratio >= bounds["minimum_content_height_ratio"]
