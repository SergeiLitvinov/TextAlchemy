"""Release gates reject stale dependencies, unknown licences and unsafe archives."""

import copy
import json
from pathlib import Path

import pytest

from tools import dependencies, release, versioning

ROOT = Path(__file__).resolve().parents[1]


def copy_inventory(tmp_path):
    (tmp_path / "contracts").mkdir()
    records = json.loads((ROOT / 'contracts/dependencies.json').read_text(encoding='utf-8'))['packages']
    files = {'uv.lock', 'pyproject.toml', 'contracts/dependencies.json'}
    files.update(record['license_file']['path'] for record in records if record.get('license_file'))
    files.update(notice['path'] for record in records for notice in record.get('notice_files', []))
    for name in sorted(files):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    return tmp_path


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "version", "description"])
def test_inventory_rejects_stale_or_incomplete_licence_evidence(tmp_path, mutation):
    root = copy_inventory(tmp_path)
    path = root / "contracts/dependencies.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "missing":
        data["packages"].pop()
    elif mutation == "duplicate":
        data["packages"].append(copy.deepcopy(data["packages"][0]))
    elif mutation == "version":
        data["packages"][0]["version"] = "999.0.0"
    else:
        data["packages"][0]["description"] = ""
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="inventory|Incomplete"):
        dependencies.inventory(root)


def test_ocr_profile_accepts_audited_replacement_and_rejects_unknown_linux_branch(tmp_path):
    dependencies.check_profile("ocr")
    rows, profiles = dependencies.inventory()
    assert not any(item['name'] == 'cuda-toolkit' for item in rows)
    assert ('torch', '2.10.0') in profiles['ocr']
    assert ('torchvision', '0.25.0') in profiles['ocr']
    sdk = next(item for item in rows if item["name"] == "aistudio-sdk")
    assert ("aistudio-sdk", "0.3.9") in profiles["ocr"]
    assert sdk["license"] == "Apache-2.0"
    assert sdk["status"] == "license-file"
    for name in ("base", "web", "html", "epub", "docs", "build"):
        dependencies.check_profile(name)
    root = copy_inventory(tmp_path)
    path = root / 'contracts/dependencies.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    runtime = next(item for item in data['packages'] if item['name'] == 'nvidia-cuda-runtime-cu12')
    runtime.update(license='UNKNOWN', status='unresolved')
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='^Unresolved dependency licences: nvidia-cuda-runtime-cu12$'):
        dependencies.check_profile('ocr', root)
    dependencies.check_profile('base', root)


def test_inventory_rejects_changed_dependency_notice(tmp_path):
    root = copy_inventory(tmp_path)
    data = json.loads((root / 'contracts/dependencies.json').read_text(encoding='utf-8'))
    torch = next(item for item in data['packages'] if item['name'] == 'torch')
    notice = root / torch['notice_files'][0]['path']
    notice.write_text('Changed upstream attribution', encoding='utf-8')
    with pytest.raises(ValueError, match='Dependency licence file changed: torch'):
        dependencies.inventory(root)


@pytest.mark.parametrize("mutation", ["wheel", "text", "escape"])
def test_inventory_binds_licence_evidence_to_locked_wheel_and_local_text(tmp_path, mutation):
    root = copy_inventory(tmp_path)
    path = root / "contracts/dependencies.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    sdk = next(item for item in data["packages"] if item["name"] == "aistudio-sdk")
    if mutation == "wheel":
        sdk["inspected_wheel_sha256"] = "0" * 64
    elif mutation == "text":
        (root / sdk["license_file"]["path"]).write_text("Changed terms", encoding="utf-8")
    else:
        sdk["license_file"]["path"] = "pyproject.toml"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="wheel differs|licence file"):
        dependencies.inventory(root)


@pytest.mark.parametrize("profile", ["docx", "pptx", "pdf"])
def test_release_blocks_unresolved_lxml_resources_before_archive_access(tmp_path, profile):
    with pytest.raises(ValueError, match="Unresolved dependency licences: lxml"):
        release.check(tmp_path, profile=profile)


def test_profiles_include_library_extras_and_all_python_versions():
    rows, profiles = dependencies.inventory()
    assert ("pymupdf", "1.27.2.3") in profiles["pdf"]
    assert ("pymupdf", "1.27.2.3") not in profiles["base"]
    assert not {"ebooklib", "lxml"}.intersection(name for name, _ in profiles["epub"])
    assert ("fonttools", next(item["version"] for item in rows if item["name"] == "fonttools")) in profiles["base"]
    tifffile = {(item["name"], item["version"]) for item in rows if item["name"] == "tifffile"}
    assert len(tifffile) == 2
    assert tifffile.issubset(profiles["ocr"])


@pytest.mark.parametrize("name", ["../private.txt", "/etc/passwd", "C:/private.txt", "x\\y", "doc/history/old.md",
                                  ".textalchemy/data.db", "src/__pycache__/x.pyc", "todo-old.md"])
def test_release_rejects_traversal_user_data_and_retired_docs(name):
    with pytest.raises(ValueError):
        release.validate_paths([name])


def test_release_rejects_duplicate_entries():
    with pytest.raises(ValueError, match="Duplicate"):
        release.validate_paths(["LICENSE", "LICENSE"])


def test_release_tag_must_match_application_version_before_archive_access(tmp_path):
    with pytest.raises(ValueError, match="tag"):
        release.check(tmp_path, tag="v999.0.0")


def test_bundled_help_requires_matching_version_and_licence_texts():
    project = __import__("tomllib").loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    data = (ROOT / "src/textalchemy/web/assets/documentation.zip").read_bytes()
    release.validate_help(data, project["version"])
    with pytest.raises(ValueError, match="version"):
        release.validate_help(data, "999.0.0")


@pytest.mark.parametrize("selector,expected", [("current", "0.2.0rc1"), ("patch", "0.2.1"),
                                             ("minor", "0.3.0"), ("major", "1.0.0"), ("0.2.0", "0.2.0")])
def test_release_version_selectors(selector, expected):
    assert versioning.select(selector, "0.2.0rc1") == expected


@pytest.mark.parametrize("version", ["0.1.0", "0.2.0b1", "v0.2.0", "0.2", "0.02.0", "0.2.0rc0", "0.2.0; echo x"])
def test_release_version_rejects_invalid_or_older_numbers(version):
    with pytest.raises(ValueError):
        versioning.select(version, "0.2.0rc1")


def test_version_update_changes_only_application_lock_record(tmp_path):
    for name in ("pyproject.toml", "uv.lock", "README.md", "doc/development/releases.md"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    before = __import__("tomllib").loads((tmp_path / "uv.lock").read_text(encoding="utf-8"))["package"]
    next_version = versioning.select("patch", versioning.current(tmp_path))
    versioning.set_version(next_version, tmp_path)
    after = __import__("tomllib").loads((tmp_path / "uv.lock").read_text(encoding="utf-8"))["package"]
    assert versioning.current(tmp_path) == next_version
    assert [item for item in before if item["name"] != "textalchemy"] == [
        item for item in after if item["name"] != "textalchemy"
    ]
