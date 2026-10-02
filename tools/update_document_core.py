"""Проверка готового wheel OpenDoc и обновление зависимости приложения."""

import argparse
import ast
import email.parser
import hashlib
import json
import re
import subprocess
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "vendor/opendoc"


def update(wheel: Path) -> Path:
    wheel = wheel.resolve(strict=True)
    if wheel.suffix != ".whl":
        raise ValueError("Expected an OpenDoc wheel")
    consumer = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("Expected exactly one distribution in the wheel")
        metadata = email.parser.Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
        if metadata["Name"] != "opendoc" or not metadata["Version"]:
            raise ValueError("Expected an OpenDoc distribution")
        if any(
            not re.fullmatch(r"extra\s*==\s*['\"][A-Za-z0-9_.-]+['\"]", dependency.partition(";")[2].strip())
            for dependency in metadata.get_all("Requires-Dist", [])
        ):
            raise ValueError("OpenDoc must not have mandatory external dependencies")
        if not wheel.name.startswith(f"opendoc-{metadata['Version']}-"):
            raise ValueError("Wheel filename must match the distribution version")
        requirement = f"opendoc=={metadata['Version']}"
        if requirement not in consumer["project"]["dependencies"]:
            raise ValueError(f"Update the application requirement before bundling {requirement}")
        expected = consumer["tool"]["uv"]["sources"]["opendoc"]["path"]
        if (ROOT / expected).resolve() != (BUNDLE / wheel.name).resolve():
            raise ValueError("Update the application wheel path before bundling this release")
        modules = {}
        for name in archive.namelist():
            if not name.startswith(("opendoc/", "opendoc-")) or ".." in Path(name).parts or "\\" in name:
                raise ValueError("Wheel contains files outside the OpenDoc package")
            if name.startswith("opendoc/") and name.endswith(".py"):
                data = archive.read(name)
                tree = ast.parse(data.decode("utf-8"))
                for node in ast.walk(tree):
                    names = (
                        [alias.name for alias in node.names]
                        if isinstance(node, ast.Import)
                        else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                    )
                    if any(name == "textalchemy" or name.startswith("textalchemy.") for name in names):
                        raise ValueError("OpenDoc must not import its consumer")
                modules[name] = hashlib.sha256(data).hexdigest()
    if not modules:
        raise ValueError("Wheel has no document library modules")
    previous = None
    manifest_path = BUNDLE / "provenance.json"
    if manifest_path.exists():
        previous_name = json.loads(manifest_path.read_text(encoding="utf-8"))["wheel"]
        previous = BUNDLE / previous_name
        if previous.resolve().parent != BUNDLE.resolve() or previous.suffix != ".whl":
            raise ValueError("Previous wheel must stay inside the application bundle")
    manifest = {
        "project": "OpenDoc",
        "distribution": metadata["Name"],
        "version": metadata["Version"],
        "wheel": wheel.name,
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "modules": modules,
        "update": "uv run python -m tools.update_document_core --wheel path/to/opendoc.whl",
    }
    BUNDLE.mkdir(parents=True, exist_ok=True)
    # Close the source archive before replacing a bundled wheel on Windows.
    target = BUNDLE / wheel.name
    temporary = target.with_suffix(".whl.tmp")
    temporary.write_bytes(wheel.read_bytes())
    temporary.replace(target)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if previous is not None and previous != target and previous.exists():
        previous.unlink()
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    print(update(parser.parse_args().wheel))
    subprocess.run(["uv", "lock", "--refresh-package", "opendoc"], cwd=ROOT, check=True)
    print("Lockfile updated; synchronize the environment before running checks.")


if __name__ == "__main__":
    main()
