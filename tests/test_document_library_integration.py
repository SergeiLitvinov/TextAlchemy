"""Application compatibility and one-way document library dependencies."""

import ast
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from opendoc import DocumentModel, Paragraph, document_from_json, document_to_dict, inspect_document_model

from textalchemy.core.document_codec import document_from_json as legacy_loads
from textalchemy.core.document_model import DocumentModel as LegacyDocumentModel
from textalchemy.core.document_model import Paragraph as LegacyParagraph
from textalchemy.core.inspection import inspect_document_model as legacy_inspect


def test_application_imports_are_exactly_the_library_types_and_functions():
    from opendoc import ArtifactLimitError

    from textalchemy.core.artifacts import ArtifactLimitError as LegacyArtifactLimitError

    assert LegacyArtifactLimitError is ArtifactLimitError
    assert LegacyDocumentModel is DocumentModel
    assert LegacyParagraph is Paragraph
    assert legacy_inspect is inspect_document_model


@pytest.mark.parametrize("format_name", ["textalchemy.document", "opendoc.document"])
def test_application_reads_both_identifiers_without_mutating_payload(format_name):
    from textalchemy.core.document_codec import document_from_dict

    payload = document_to_dict(DocumentModel())
    payload["format"] = format_name
    assert isinstance(document_from_dict(payload), DocumentModel)
    assert payload["format"] == format_name
    assert isinstance(legacy_loads(json.dumps(payload)), DocumentModel)


def test_independent_library_rejects_application_identifier():
    payload = document_to_dict(DocumentModel())
    payload["format"] = "textalchemy.document"
    with pytest.raises(ValueError, match="unsupported document format"):
        document_from_json(json.dumps(payload))


def test_document_library_never_imports_the_consuming_application():
    import opendoc

    source = Path(opendoc.__file__).parent
    assert list(source.glob("*.py")), "Library modules must actually be inspected"
    for path in source.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [node.module or ""]
            else:
                continue
            assert not any(name == "textalchemy" or name.startswith("textalchemy.") for name in imports), path


def test_bundled_wheel_matches_provenance_and_installed_modules():
    import opendoc

    bundle = Path(__file__).parents[1] / "vendor/opendoc"
    provenance = json.loads((bundle / "provenance.json").read_text(encoding="utf-8"))
    wheel = bundle / provenance["wheel"]
    assert provenance["distribution"] == "opendoc"
    assert list(bundle.glob("*.whl")) == [wheel]
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == provenance["sha256"]
    assert provenance["modules"]
    with zipfile.ZipFile(wheel) as archive:
        for name, digest in provenance["modules"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
            installed = Path(opendoc.__file__).parent / name.split("/", 1)[1]
            assert hashlib.sha256(installed.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("format_name", ["textalchemy.document", "opendoc.document"])
def test_native_semantics_survive_application_json(format_name):
    from opendoc import (
        Anchor,
        Footnote,
        FootnoteReference,
        Heading,
        InternalLink,
        ListItem,
        Section,
        TextRun,
        get_anchor,
        get_footnote_reference,
        get_heading,
        get_internal_link,
        get_list_item,
        set_anchor,
        set_footnote,
        set_footnote_reference,
        set_heading,
        set_internal_link,
        set_list_item,
    )

    from textalchemy.core.document_codec import document_from_dict
    from textalchemy.core.document_codec import document_to_dict as application_dump

    heading = Paragraph([TextRun("Title")])
    item = Paragraph([TextRun("Item"), TextRun("")])
    set_heading(heading, Heading(2))
    set_anchor(heading, Anchor("target"))
    set_list_item(item, ListItem("list-1", level=0, kind="ordered"))
    set_internal_link(item.content[0], InternalLink("target"))
    set_footnote_reference(item.content[1], FootnoteReference("note-1"))
    document = DocumentModel(sections=[Section(blocks=[heading, item])])
    set_footnote(document, Footnote("note-1", [Paragraph([TextRun("Note")])]))
    payload = application_dump(document)
    payload["format"] = format_name
    restored = document_from_dict(payload)
    assert not restored.validate()
    restored_heading, restored_item = restored.sections[0].blocks
    assert get_heading(restored_heading) == Heading(2)
    assert get_anchor(restored_heading) == Anchor("target")
    assert get_list_item(restored_item) == get_list_item(item)
    assert get_internal_link(restored_item.content[0]) == InternalLink("target")
    assert get_footnote_reference(restored_item.content[1]) == FootnoteReference("note-1")
    assert restored.footnotes[0].blocks[0].plain_text == "Note"


def test_native_version_one_attachments_are_not_application_migrations():
    from opendoc import Resource, ResourceKind

    from textalchemy.core.document_codec import document_from_dict

    document = DocumentModel()
    document.add_resource(Resource("docx-theme", ResourceKind.ATTACHMENT, "application/xml", data=b"<theme/>"))
    payload = document_to_dict(document)
    payload["version"] = 1
    restored = document_from_dict(payload)
    assert restored.package is None
    assert restored.resources["docx-theme"].data == b"<theme/>"


def test_application_saved_file_is_readable_by_standalone_opendoc(tmp_path):
    from opendoc import Section, TextRun, load_document

    from textalchemy.core.document_codec import save_document

    document = DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("Interoperable")])])])
    path = save_document(document, tmp_path / "document.json")
    assert json.loads(path.read_text(encoding="utf-8"))["format"] == "opendoc.document"
    assert load_document(path).sections[0].blocks[0].plain_text == "Interoperable"


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_invalid_model_does_not_replace_existing_output(tmp_path, value):
    from opendoc import Section, TextRun

    from textalchemy.convert.pptx_writer import write_pptx_model
    from textalchemy.core.document_codec import save_document

    document = DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("Text")], properties={"value": value})])])
    json_path, pptx_path = tmp_path / "old.json", tmp_path / "old.pptx"
    json_path.write_bytes(b"previous JSON")
    pptx_path.write_bytes(b"previous PPTX")
    with pytest.raises(ValueError, match="finite"):
        save_document(document, json_path)
    assert not write_pptx_model(document, pptx_path).success
    assert json_path.read_bytes() == b"previous JSON"
    assert pptx_path.read_bytes() == b"previous PPTX"


def test_unscoped_inspection_does_not_claim_complete_resource_retention():
    from opendoc import DocumentInspection, compare_inspections

    source = DocumentInspection(None, "pdf", resources=[{"id": "one", "sha256": "a" * 64, "size_bytes": 1}])
    target = DocumentInspection(None, "pdf", resources=[{"id": "one", "sha256": "a" * 64, "size_bytes": 1}])
    comparison = compare_inspections(source, target)
    assert comparison.resource_comparison["exact_hash_retention_ratio"] is None
    assert comparison.geometry_summary["available"] is False
