"""Protect release provenance and prevent new native format workarounds."""

import hashlib
import json
import zipfile

import pytest

from tools.check_library_contracts import check_bundle, check_source_boundary
from tools.update_format_adapters import update


def test_boundary_rejects_new_engine_bridge(tmp_path):
    source = tmp_path / "src/textalchemy/new_reader.py"
    source.parent.mkdir(parents=True)
    source.write_text("import docx\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Native engine imports changed"):
        check_source_boundary(tmp_path, {"compatibility_aliases": {}, "native_engine_bridges": {}})


def test_boundary_cannot_be_bypassed_by_adding_engine_exceptions(tmp_path):
    with pytest.raises(ValueError, match="exceptions are no longer allowed"):
        check_source_boundary(
            tmp_path,
            {
                "compatibility_aliases": {},
                "native_engine_bridges": {"src/textalchemy/new_reader.py": {"engines": ["docx"]}},
            },
        )


def test_boundary_rejects_implementation_in_facade(tmp_path):
    source = tmp_path / "src/textalchemy/formats/txt.py"
    source.parent.mkdir(parents=True)
    source.write_text("def parse(value):\n    return value\n", encoding="utf-8")
    contract = {"compatibility_aliases": {"src/textalchemy/formats/txt.py": "opendoc_formats.readers.txt"}}
    with pytest.raises(ValueError, match="must not implement"):
        check_source_boundary(tmp_path, contract)
    source.write_text("class DocumentModel:\n    pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="copy of the document model"):
        check_source_boundary(tmp_path, {"compatibility_aliases": {}, "native_engine_bridges": {}})


@pytest.mark.parametrize(
    "code",
    [
        "from opendoc.document_model import _private\n",
        "from opendoc_formats.native.docx_package import NativePackage\n",
        "import opendoc_formats.native.docx_package\n",
        "from opendoc_formats import native\n",
        "from importlib import import_module\nmodule = import_module('opendoc_formats.native.docx_package')\n",
    ],
)
def test_boundary_rejects_private_library_import(tmp_path, code):
    source = tmp_path / "src/textalchemy/bypass.py"
    source.parent.mkdir(parents=True)
    source.write_text(code, encoding="utf-8")
    with pytest.raises(ValueError, match="Private library import"):
        check_source_boundary(tmp_path, {"compatibility_aliases": {}, "native_engine_bridges": {}})


@pytest.mark.parametrize(
    "source_code",
    [
        "import importlib\nengine = importlib.import_module('fitz')\n",
        "from importlib import import_module\nengine = import_module('docx')\n",
        "engine = __import__('lxml.etree')\n",
    ],
)
def test_boundary_rejects_dynamic_engine_import(tmp_path, source_code):
    source = tmp_path / "src/textalchemy/bypass.py"
    source.parent.mkdir(parents=True)
    source.write_text(source_code, encoding="utf-8")
    with pytest.raises(ValueError, match="Native engine imports changed"):
        check_source_boundary(tmp_path, {"compatibility_aliases": {}, "native_engine_bridges": {}})


@pytest.mark.parametrize(
    "source_code",
    [
        "PART = 'word/document.xml'\n",
        "W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'\n",
        "from xml.etree import ElementTree\n",
        "from xml import etree\n",
        "import xml\n",
        "from importlib import import_module\nmodule = import_module('xml.etree.ElementTree')\n",
    ],
)
def test_boundary_rejects_native_document_structure(tmp_path, source_code):
    source = tmp_path / "src/textalchemy/bypass.py"
    source.parent.mkdir(parents=True)
    source.write_text(source_code, encoding="utf-8")
    with pytest.raises(ValueError, match="belongs to OpenDoc Formats"):
        check_source_boundary(tmp_path, {"compatibility_aliases": {}, "native_engine_bridges": {}})


def test_release_check_rejects_changed_installed_resource(tmp_path):
    wheel = tmp_path / "opendoc_formats-0.2.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("opendoc_formats/assets/file.lua", b"original")
    digest = hashlib.sha256(b"original").hexdigest()
    manifest = {
        "distribution": "opendoc-formats",
        "version": "0.2.0",
        "wheel": wheel.name,
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "modules": {},
        "files": {"opendoc_formats/assets/file.lua": digest},
        "source": {
            "url": "https://github.com/SergeiLitvinov/opendoc-formats/releases/download/v0.2.0/" + wheel.name,
            "checksum_verified": True,
        },
    }
    (tmp_path / "provenance.json").write_text(json.dumps(manifest), encoding="utf-8")
    installed = tmp_path / "installed/assets/file.lua"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"modified")
    with pytest.raises(ValueError, match="differs from release"):
        check_bundle(tmp_path, tmp_path / "installed")


def test_adapter_update_rejects_wrong_checksum_before_writing(tmp_path):
    wheel = tmp_path / "untrusted.whl"
    wheel.write_bytes(b"untrusted")
    with pytest.raises(ValueError, match="checksum"):
        update(wheel, sha256="0" * 64, source_url="", source_ref="")


def test_adapter_upgrade_replaces_only_previous_verified_wheel(tmp_path, monkeypatch):
    from tools import update_format_adapters

    monkeypatch.setattr(update_format_adapters, "ROOT", tmp_path)
    bundle = tmp_path / "vendor/opendoc-formats"
    bundle.mkdir(parents=True)
    previous = bundle / "opendoc_formats-0.2.0-py3-none-any.whl"
    previous.write_bytes(b"previous verified release")
    (bundle / "provenance.json").write_text(
        json.dumps(
            {
                "wheel": previous.name,
                "sha256": hashlib.sha256(previous.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    wheel = tmp_path / "opendoc_formats-0.3.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("opendoc_formats/__init__.py", "")
        archive.writestr(
            "opendoc_formats-0.3.0.dist-info/METADATA", "Name: opendoc-formats\nVersion: 0.3.0\nRequires-Dist: opendoc==0.1.0\n"
        )
    (tmp_path / "pyproject.toml").write_text(
        """[project]
dependencies = ["opendoc==0.1.0", "opendoc-formats[pdf-text,fonts]==0.3.0"]
[tool.uv.sources]
opendoc-formats = {path = "vendor/opendoc-formats/opendoc_formats-0.3.0-py3-none-any.whl"}
""",
        encoding="utf-8",
    )
    target = update(
        wheel,
        sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
        source_url="https://github.com/SergeiLitvinov/opendoc-formats/releases/download/v0.3.0/" + wheel.name,
        source_ref="a" * 40,
    )
    assert list(bundle.glob("*.whl")) == [target]
    assert target.read_bytes() == wheel.read_bytes()
    assert json.loads((bundle / "provenance.json").read_text())["version"] == "0.3.0"
