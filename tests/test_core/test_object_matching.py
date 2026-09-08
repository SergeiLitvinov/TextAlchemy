"""Mutation cases for occurrence-preserving structural comparison."""

from textalchemy.core.document_model import DocumentModel, Paragraph, Provenance, Section, TextRun
from textalchemy.core.inspection import compare_inspections, inspect_document_model


def _inspect(*texts, provenance=None):
    return inspect_document_model(DocumentModel(sections=[Section(blocks=[
        Paragraph(content=[TextRun(text)], provenance=provenance) for text in texts
    ])]))


def _assert_accounted(diff):
    matched = diff["retained"] + diff["changed"]
    assert len(matched) + len(diff["lost"]) == diff["source_count"]
    assert len(matched) + len(diff["added"]) == diff["target_count"]
    assert len({item["source_index"] for item in matched}) == len(matched)
    assert len({item["target_index"] for item in matched}) == len(matched)


def test_reordering_without_provenance_is_a_move_not_content_loss():
    diff = compare_inspections(_inspect("First", "Second"), _inspect("Second", "First")).object_diff
    _assert_accounted(diff)
    assert diff["lost"] == diff["added"] == []
    assert len(diff["changed"]) == 2
    assert all(item["changes"] == ["location"] for item in diff["changed"])
    assert all(item["match_basis"] == "content" for item in diff["changed"])


def test_deleting_first_object_does_not_mark_shifted_objects_as_edited():
    before, after = _inspect("Deleted", "Kept", "Also kept"), _inspect("Kept", "Also kept")
    diff = compare_inspections(before, after).object_diff
    _assert_accounted(diff)
    assert diff["lost"] == [before.objects[0]]
    assert diff["added"] == []
    assert all(item["changes"] == ["location"] for item in diff["changed"])


def test_shared_provenance_does_not_collapse_occurrences():
    origin = Provenance(source_format="pptx", object_id="group-1")
    before = _inspect("First", "Second", "Third", provenance=origin)
    after = _inspect("Third", "First", provenance=origin)
    diff = compare_inspections(before, after).object_diff
    _assert_accounted(diff)
    assert diff["lost"] == [before.objects[1]]
    assert diff["retention_ratio"] == 0.6667


def test_identical_duplicate_removal_is_counted_once_and_pairing_is_ambiguous():
    diff = compare_inspections(_inspect("Same", "Same", "Same"), _inspect("Same", "Same")).object_diff
    _assert_accounted(diff)
    assert len(diff["lost"]) == 1
    assert diff["matching"]["ambiguous"] == 2


def test_edit_in_place_is_explicitly_heuristic_without_provenance():
    diff = compare_inspections(_inspect("Before"), _inspect("After")).object_diff
    assert diff["changed"][0]["changes"] == ["content_hash"]
    assert diff["matching"]["heuristic"] == 1


def test_conflicting_origins_in_same_source_are_not_merged_by_equal_text():
    before = _inspect("Same", provenance=Provenance(source_format="pptx", object_id="shape-1"))
    after = _inspect("Same", provenance=Provenance(source_format="pptx", object_id="shape-2"))
    diff = compare_inspections(before, after).object_diff
    assert len(diff["lost"]) == len(diff["added"]) == 1


def test_reimported_format_can_match_content_despite_new_origins():
    before = _inspect("Same", provenance=Provenance(source_format="pptx", object_id="shape-1"))
    after = _inspect("Same", provenance=Provenance(source_format="docx", object_id="paragraph-1"))
    diff = compare_inspections(before, after).object_diff
    assert not diff["lost"]
    assert diff["retained"][0]["match_basis"] == "content"


def test_page_provenance_without_object_id_is_not_unique_identity():
    inspection = _inspect("First", "Second", provenance=Provenance(source_format="pdf", page=1))
    assert all(item["provenance"]["identity"] is None for item in inspection.objects)


def test_missing_inventory_is_unknown_not_total_loss():
    from textalchemy.core.inspection import DocumentInspection

    comparison = compare_inspections(_inspect("Text"), DocumentInspection(None, "html"))
    diff = comparison.object_diff
    assert diff["available"] is False
    assert diff["retention_ratio"] is None
    assert diff["lost"] == []
    assert not any(issue.feature == "object-loss" for issue in comparison.issues)


def test_known_empty_inventory_still_detects_real_deletion():
    diff = compare_inspections(_inspect("Text"), _inspect()).object_diff
    assert diff["available"] is True
    assert len(diff["lost"]) == 1
    assert diff["retention_ratio"] == 0


def test_docx_reexport_detects_deletion_and_moves_without_provenance_carryover(tmp_path):
    from textalchemy.convert.docx_writer import write_docx_model
    from textalchemy.formats.docx import read_docx_model

    source_path, target_path = tmp_path / "source.docx", tmp_path / "edited.docx"
    original = DocumentModel(sections=[Section(blocks=[
        Paragraph(content=[TextRun(text)]) for text in ["Delete me", "Move me", "Keep me", "Keep me"]
    ])])
    assert write_docx_model(original, source_path).success
    document = read_docx_model(source_path)
    before = inspect_document_model(document)
    blocks = document.sections[0].blocks
    document.sections[0].blocks = [blocks[2], blocks[3], blocks[1]]
    assert write_docx_model(document, target_path).success
    restored = read_docx_model(target_path)
    assert [block.plain_text for block in restored.sections[0].blocks] == ["Keep me", "Keep me", "Move me"]
    diff = compare_inspections(before, inspect_document_model(restored)).object_diff
    _assert_accounted(diff)
    assert diff["lost"] == [before.objects[0]]
    assert diff["added"] == []
    assert len(diff["retained"]) + len(diff["changed"]) == 3


def test_images_match_by_bytes_not_package_resource_ids():
    from textalchemy.core.document_model import Image, Resource, ResourceKind

    def image_inspection(resource_id, data):
        return inspect_document_model(DocumentModel(
            resources={resource_id: Resource(resource_id, ResourceKind.RASTER_IMAGE, "image/png", data=data)},
            sections=[Section(blocks=[Image(resource_id=resource_id)])],
        ))

    source = image_inspection("image-1", b"first image")
    renamed = image_inspection("image-9", b"first image")
    replaced = image_inspection("image-1", b"different image")
    diff = compare_inspections(source, renamed).object_diff
    assert len(diff["retained"]) == 1
    assert diff["retained"][0]["match_basis"] == "content"
    assert compare_inspections(source, replaced).object_diff["changed"][0]["changes"] == ["content_hash"]
