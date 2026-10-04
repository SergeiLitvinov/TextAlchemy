"""Потребитель принимает готовый пакет без изменения проекта библиотеки."""

import hashlib
import json
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from tools import update_document_core as updater

ReleaseFixture = tuple[Callable[..., Path], Path]


@pytest.fixture
def release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ReleaseFixture:
    root = tmp_path / "application"
    root.mkdir()
    bundle = root / "vendor/opendoc"
    monkeypatch.setattr(updater, "ROOT", root)
    monkeypatch.setattr(updater, "BUNDLE", bundle)
    (root / "pyproject.toml").write_text(
        '[project]\ndependencies=["opendoc==0.1.0"]\n'
        '[tool.uv.sources]\nopendoc={path="vendor/opendoc/opendoc-0.1.0-py3-none-any.whl"}\n',
        encoding="utf-8",
    )

    def build(
        *,
        name: str = "opendoc",
        version: str = "0.1.0",
        dependencies: str = "",
        code: str = "class Document: pass\n",
        extra: str | None = None,
    ) -> Path:
        wheel = tmp_path / f"opendoc-{version}-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(f"opendoc-{version}.dist-info/METADATA", f"Name: {name}\nVersion: {version}\n{dependencies}")
            archive.writestr("opendoc/__init__.py", code)
            if extra:
                archive.writestr(extra, "external")
        return wheel

    return build, bundle


def test_update_copies_artifact_without_building_source_and_records_hashes(
    release: ReleaseFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build, bundle = release
    wheel = build(dependencies='Requires-Dist: lxml; extra == "math"\n')
    original = wheel.read_bytes()

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("The consuming updater must not build or execute the library")

    monkeypatch.setattr(updater.subprocess, "run", forbidden)
    target = updater.update(wheel)
    assert target.read_bytes() == wheel.read_bytes() == original
    provenance = json.loads((bundle / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["sha256"] == hashlib.sha256(original).hexdigest()
    assert provenance["distribution"] == "opendoc" and provenance["version"] == "0.1.0"
    assert "--wheel" in provenance["update"] and "--source" not in provenance["update"]
    assert updater.update(target) == target  # Reaccepting the bundled wheel is safe.


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "other"},
        {"version": "0.2.0"},
        {"dependencies": "Requires-Dist: textalchemy\n"},
        {"dependencies": 'Requires-Dist: dependency; extra == "math" or python_version >= "3.11"\n'},
        {"code": "from textalchemy.core import document_model\n"},
        {"extra": "../opendoc/escape.py"},
        {"extra": "other_package/__init__.py"},
    ],
)
def test_invalid_release_preserves_existing_bundle(release: ReleaseFixture, changes: dict[str, str]) -> None:
    build, bundle = release
    target = updater.update(build())
    original_wheel = target.read_bytes()
    original_manifest = (bundle / "provenance.json").read_bytes()
    with pytest.raises(ValueError):
        updater.update(build(**changes))
    assert target.read_bytes() == original_wheel
    assert (bundle / "provenance.json").read_bytes() == original_manifest


def test_upgrade_retires_only_the_previous_bundled_artifact(release: ReleaseFixture) -> None:
    build, bundle = release
    source = build()
    previous = updater.update(source)
    project = updater.ROOT / "pyproject.toml"
    project.write_text(project.read_text(encoding="utf-8").replace("0.1.0", "0.2.0"), encoding="utf-8")
    target = updater.update(build(version="0.2.0"))
    assert target.exists() and not previous.exists()
    assert source.exists()  # The release producer's copy is never removed.
    assert list(bundle.glob("*.whl")) == [target]


def test_manifest_cannot_retire_an_artifact_outside_the_bundle(release: ReleaseFixture) -> None:
    build, bundle = release
    wheel = build()
    updater.update(wheel)
    outside = updater.ROOT / "outside.whl"
    outside.write_bytes(b"preserve")
    manifest = bundle / "provenance.json"
    manifest.write_text('{"wheel": "../../outside.whl"}', encoding="utf-8")
    with pytest.raises(ValueError, match="inside"):
        updater.update(wheel)
    assert outside.read_bytes() == b"preserve"


def test_published_checksum_and_reference_are_recorded(release: ReleaseFixture) -> None:
    build, bundle = release
    wheel = build()
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    updater.update(wheel, sha256=digest.upper(), source_url="https://example.org/opendoc.whl", source_ref="commit-id")
    manifest = json.loads((bundle / "provenance.json").read_text(encoding="utf-8"))
    assert manifest["sha256"] == digest
    assert manifest["source"] == {
        "url": "https://example.org/opendoc.whl", "ref": "commit-id", "checksum_verified": True,
    }
    original = (bundle / "provenance.json").read_bytes()
    with pytest.raises(ValueError, match="checksum"):
        updater.update(wheel, sha256="0" * 64)
    assert (bundle / "provenance.json").read_bytes() == original
    assert (bundle / wheel.name).read_bytes() == wheel.read_bytes()


def test_incomplete_release_reference_is_rejected(release: ReleaseFixture) -> None:
    build, bundle = release
    with pytest.raises(ValueError, match="together"):
        updater.update(build(), source_url="https://example.org/opendoc.whl")
    assert not bundle.exists()
