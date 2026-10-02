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
