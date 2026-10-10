"""Validate application release archives and write a manifest; never publish or tag."""

import argparse
import hashlib
import io
import json
import re
import tarfile
import tomllib
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from tools.dependencies import check_profile, inventory

ROOT = Path(__file__).resolve().parents[1]
LICENSES = ("doc/LICENSE", "doc/NOTICE", "doc/licenses/lunr-MIT.txt", "doc/licenses/lunr-languages-MPL-1.1.txt",
            "doc/licenses/mkdocs-BSD-3-Clause.txt", "doc/licenses/umd-MIT.txt", "doc/licenses/python-docx-MIT.txt",
            "doc/licenses/aistudio-sdk-Apache-2.0.txt")


def validate_paths(names: list[str]) -> None:
    """Reject traversal, duplicate entries, user data and development caches before reading."""
    if len(set(names)) != len(names):
        raise ValueError("Duplicate archive entries")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
            raise ValueError(f"Unsafe archive path: {name}")
        if any(part in {".textalchemy", ".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
                        "history", "build", "dist"} for part in path.parts):
            raise ValueError(f"Development/user data in release: {name}")
        if path.suffix in {".pyc", ".pyo", ".sqlite", ".db", ".log"} or path.name.lower().startswith("todo-"):
            raise ValueError(f"Unwanted release file: {name}")


def validate_help(data: bytes, version: str) -> None:
    with ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        validate_paths(names)
        required = {"index.html", "doc/guide/index.html", "doc/reference/dependencies/index.html",
                    "doc/development/licenses/index.html", "search/lunr.js", "search/lunr.ru.js"}
        if not required.issubset(names):
            raise ValueError("Incomplete bundled documentation")
        if version not in archive.read("index.html").decode("utf-8"):
            raise ValueError("Documentation version differs from package")
        for license_path in LICENSES:
            if f"files/{license_path}" not in names:
                raise ValueError(f"Licence notice missing from help: {license_path}")


def validate_wheel(path: Path, project: dict, help_data: bytes) -> None:
    with ZipFile(path) as archive:
        names = archive.namelist()
        validate_paths(names)
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("Invalid wheel metadata count")
        metadata_path = metadata_names[0]
        metadata = BytesParser().parsebytes(archive.read(metadata_path))
        if metadata["Name"] != "textalchemy" or metadata["Version"] != project["version"]:
            raise ValueError("Wheel name/version differs from pyproject")
        if metadata["License-Expression"] != project["license"]:
            raise ValueError("Wheel licence expression differs from pyproject")
        dist_info = metadata_path.removesuffix("METADATA")
        for name in LICENSES:
            if dist_info + "licenses/" + name not in names:
                raise ValueError(f"Licence text missing from wheel: {name}")
        requirements = metadata.get_all("Requires-Dist", [])
        for requirement in ("opendoc-model==0.7.2", "opendoc-formats[fonts,pdf-text]==0.19.1"):
            if requirement not in requirements:
                raise ValueError(f"Missing immutable library requirement: {requirement}")
        bundled = archive.read("textalchemy/web/assets/documentation.zip")
        if bundled != help_data:
            raise ValueError("Wheel documentation differs from checked source bundle")
        if any(name.startswith(("opendoc_model/", "opendoc_formats/", "vendor/")) for name in names):
            raise ValueError("Library implementations must remain separate wheels")
        validate_help(bundled, project["version"])


def validate_sdist(path: Path, root: Path, project: dict) -> None:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        validate_paths([member.name for member in members])
        if any(not (member.isfile() or member.isdir()) for member in members):
            raise ValueError("Links or special files are forbidden in the sdist")
        prefix = f"textalchemy-{project['version']}/"
        if any(not member.name.startswith(prefix) and member.name != prefix.rstrip("/") for member in members):
            raise ValueError("Unexpected source distribution root")
        files = {member.name.removeprefix(prefix): member for member in members if member.isfile()}
        required = {*LICENSES, "pyproject.toml", "uv.lock", "mkdocs.yml", "README.md", "TODO.md",
                    "contracts/libraries.json", "contracts/dependencies.json", "tools/release.py",
                    "doc/development/releases.md", "tests/test_release.py"}
        required.update(script.relative_to(root).as_posix() for script in root.glob("tools/acceptance/*.ps1"))
        if not required.issubset(files):
            raise ValueError("Incomplete source distribution: " + ", ".join(sorted(required - set(files))))
        metadata = BytesParser().parsebytes(archive.extractfile(files["PKG-INFO"]).read())
        if metadata["Version"] != project["version"]:
            raise ValueError("Source distribution version differs from pyproject")
        for directory in ("opendoc-model", "opendoc-formats"):
            provenance = json.loads((root / f"vendor/{directory}/provenance.json").read_text(encoding="utf-8"))
            wheel = next((root / f"vendor/{directory}").glob("*.whl"))
            name = wheel.relative_to(root).as_posix()
            if name not in files:
                raise ValueError(f"Missing library wheel in sdist: {name}")
            actual = hashlib.sha256(archive.extractfile(files[name]).read()).hexdigest()
            if actual != provenance["sha256"]:
                raise ValueError(f"Modified library wheel in sdist: {name}")


def check(directory: Path, *, root: Path = ROOT, profile: str = "base", tag: str | None = None) -> dict:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?", version):
        raise ValueError("Use a three-component release version, optionally a/b/rc")
    if tag is not None and tag != "v" + version:
        raise ValueError("Release tag differs from pyproject version")
    records, profiles = inventory(root)
    check_profile(profile, root)
    for text_path in ("README.md", "doc/development/releases.md"):
        if version not in (root / text_path).read_text(encoding="utf-8"):
            raise ValueError(f"Release version is missing from {text_path}")
    help_data = (root / "src/textalchemy/web/assets/documentation.zip").read_bytes()
    wheel = directory / f"textalchemy-{version}-py3-none-any.whl"
    sdist = directory / f"textalchemy-{version}.tar.gz"
    validate_wheel(wheel, project, help_data)
    validate_sdist(sdist, root, project)
    artifacts = [wheel, sdist]
    for name in ("opendoc-model", "opendoc-formats"):
        artifacts.append(next((root / "vendor" / name).glob("*.whl")))
    return {
        "application": "textalchemy", "version": version, "profile": profile,
        "distribution_license": project["license"], "locked_dependency_records": len(records),
        "selected_profile_records": len(profiles[profile]),
        "scope": "Application archives and official library wheels; no engine binaries, OCR weights or extras environment",
        "artifacts": [{"file": artifact.name, "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
                      for artifact in artifacts],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--profile", default="base", help="Profile to check for unresolved licence evidence")
    parser.add_argument("--tag", help="Optional expected v-prefixed tag; does not create a tag")
    args = parser.parse_args()
    report = check(args.dist, profile=args.profile, tag=args.tag)
    args.dist.joinpath("release-manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
