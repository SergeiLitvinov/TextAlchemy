"""Recursive inventory and partial text changes are distinct from whole-object loss."""

from copy import deepcopy

from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import (
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    Paragraph,
    Provenance,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
)
from textalchemy.core.inspection import compare_inspections, inspect_document_model
from textalchemy.core.object_quality_policy import ObjectLossPolicy


def _document():
    inner = Table(rows=[TableRow(cells=[TableCell(blocks=[Paragraph(content=[TextRun("Deep text")])])])])
    paragraph = Paragraph(content=[TextRun("Cell text"), Image("picture"), Formula("x+1", FormulaFormat.LATEX)])
    outer = Table(rows=[TableRow(cells=[TableCell(blocks=[paragraph, inner])])],
                  provenance=Provenance(source_format="model", object_id="table"))
    return DocumentModel(
        sections=[Section(blocks=[outer])],
        resources={"picture": Resource("picture", ResourceKind.RASTER_IMAGE, "image/png", data=b"image")},
    )


def test_recursive_inventory_includes_nested_tables_and_inline_objects():
    inspection = inspect_document_model(_document())
    assert [item["type"] for item in inspection.objects] == ["table", "paragraph", "image", "formula", "table", "paragraph"]
    locations = {item["location"] for item in inspection.objects}
    assert all(item["parent_location"] in locations for item in inspection.objects[1:])
    assert inspection.objects[1]["text_characters"] == len("Cell text")  # formula is counted separately
    assert inspection.objects[3]["text_characters"] is None  # formula markup is not plain text


def test_inline_image_removal_is_visible_and_budgeted(tmp_path):
    source = _document()
    target = deepcopy(source)
    target.sections[0].blocks[0].rows[0].cells[0].blocks[0].content.pop(1)
    comparison = compare_inspections(inspect_document_model(source), inspect_document_model(target))
    assert [item["type"] for item in comparison.object_diff["lost"]] == ["image"]
    report = ConversionReport(tmp_path / "out.json")
    assert ObjectLossPolicy(0).evaluate(report, comparison) is False
    assert report.metrics["object_quality_gate"]["lost_objects"] == 1
    assert ObjectLossPolicy(1).evaluate(ConversionReport(tmp_path / "allowed.json"), comparison) is True


def test_removed_table_and_its_descendants_are_counted_individually(tmp_path):
    comparison = compare_inspections(inspect_document_model(_document()), inspect_document_model(DocumentModel()))
    assert len(comparison.object_diff["lost"]) == 6
    report = ConversionReport(tmp_path / "out.json")
    assert ObjectLossPolicy(5).evaluate(report, comparison) is False
    assert report.metrics["object_quality_gate"]["lost_objects"] == 6


def test_previous_inventory_scope_cannot_pass_recursive_budget(tmp_path):
    source, target = inspect_document_model(_document()), inspect_document_model(_document())
    source.metadata["object_inventory_scope"] = target.metadata["object_inventory_scope"] = "model-top-level-blocks"
    comparison = compare_inspections(source, target)
    report = ConversionReport(tmp_path / "out.json")
    assert ObjectLossPolicy().evaluate(report, comparison) is False
    assert report.metrics["object_quality_gate"]["reason"] == "unavailable"


def test_text_shortening_is_reported_separately_from_object_deletion():
    source = _document()
    target = deepcopy(source)
    target.sections[0].blocks[0].rows[0].cells[0].blocks[0].content[0].text = "Cell"
    diff = compare_inspections(inspect_document_model(source), inspect_document_model(target)).object_diff
    assert not diff["lost"]
    assert diff["content_changes"]["changed_text_objects"] == 1
    assert diff["content_changes"]["net_character_reduction"] == 5


def test_equal_length_replacement_is_not_misreported_as_unchanged():
    source = _document()
    target = deepcopy(source)
    target.sections[0].blocks[0].rows[0].cells[0].blocks[0].content[0].text = "Other txt"
    changes = compare_inspections(inspect_document_model(source), inspect_document_model(target)).object_diff["content_changes"]
    assert changes["changed_text_objects"] == 1
    assert changes["net_character_reduction"] == 0


def test_run_splitting_does_not_add_objects_or_change_text():
    source = DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun("Hello world")])])])
    target = DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun("Hello "), TextRun("world")])])])
    diff = compare_inspections(inspect_document_model(source), inspect_document_model(target)).object_diff
    assert len(diff["retained"]) == 1
    assert diff["added"] == diff["lost"] == diff["changed"] == []


def test_docx_roundtrip_exposes_paragraph_deleted_inside_cell(tmp_path):
    from textalchemy.convert.docx_writer import write_docx_model
    from textalchemy.formats.docx import read_docx_model

    source = DocumentModel(sections=[Section(blocks=[Table(rows=[TableRow(cells=[TableCell(blocks=[
        Paragraph(content=[TextRun("Remove me")]), Paragraph(content=[TextRun("Keep me")]),
    ])])])])])
    source_path, target_path = tmp_path / "source.docx", tmp_path / "target.docx"
    assert write_docx_model(source, source_path).success
    model = read_docx_model(source_path)
    before = inspect_document_model(model)
    model.sections[0].blocks[0].rows[0].cells[0].blocks.pop(0)
    assert write_docx_model(model, target_path).success
    diff = compare_inspections(before, inspect_document_model(read_docx_model(target_path))).object_diff
    assert len(diff["lost"]) == 1
    assert diff["lost"][0]["type"] == "paragraph"
    assert ".cells[0].blocks[0]" in diff["lost"][0]["location"]
