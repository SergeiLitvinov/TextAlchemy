"""Application delegates moved readers to the independently installed wheel."""

import ast
import hashlib
import importlib
import json
import zipfile
from pathlib import Path

import opendoc_formats
from opendoc_formats.readers.html import read_html_model
from opendoc_formats.readers.txt import read_txt_model

from textalchemy.formats.html_model import read_html_model as application_html_reader
from textalchemy.formats.txt import read_txt_model as application_txt_reader


def test_application_readers_are_library_functions():
    assert application_html_reader is read_html_model
    assert application_txt_reader is read_txt_model


def test_all_compatibility_modules_share_library_state():
    source = Path(__file__).parents[1] / "src/textalchemy"
    checked = []
    for path in source.rglob("*.py"):
        targets = [
            node.args[0].value
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "import_module"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value.startswith("opendoc_formats.")
        ]
        if targets:
            name = "textalchemy." + ".".join(path.relative_to(source).with_suffix("").parts)
            assert len(targets) == 1, path
            assert importlib.import_module(name) is importlib.import_module(targets[0]), name
            checked.append(name)
    assert checked


def test_format_wheel_matches_manifest_and_installed_code():
    bundle = Path(__file__).parents[1] / "vendor/opendoc-formats"
    manifest = json.loads((bundle / "provenance.json").read_text(encoding="utf-8"))
    wheel = bundle / manifest["wheel"]
    assert manifest["distribution"] == "opendoc-formats"
    assert manifest["scope"] == [
        "txt",
        "html",
        "docx",
        "epub",
        "pdf",
        "pptx",
        "djvu",
        "json",
        "latex",
        "exports",
        "fonts",
        "ooxml",
    ]
    assert list(bundle.glob("*.whl")) == [wheel]
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == manifest["sha256"]
    with zipfile.ZipFile(wheel) as archive:
        for name, digest in manifest["modules"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
            installed = Path(opendoc_formats.__file__).parent / name.split("/", 1)[1]
            assert hashlib.sha256(installed.read_bytes()).hexdigest() == digest


def test_format_package_has_no_back_dependency_or_copied_model():
    source = Path(opendoc_formats.__file__).parent
    assert not (source / "document_model.py").exists()
    for path in source.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            )
            assert not any(name == "textalchemy" or name.startswith("textalchemy.") for name in names), path
