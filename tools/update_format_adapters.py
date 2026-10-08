"""Bundle a checksum-verified OpenDoc Formats release without rebuilding it."""

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


def update(wheel: Path, *, sha256: str, source_url: str, source_ref: str) -> Path:
    """Validate the published distribution before changing the application bundle."""
    data = wheel.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", sha256.lower()) or digest != sha256.lower():
        raise ValueError("Wheel checksum does not match the published SHA-256")
    if not re.fullmatch(r"[0-9a-f]{40}", source_ref):
        raise ValueError("Source reference must be an immutable upstream commit")
    consumer = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("Expected one distribution")
        metadata = email.parser.Parser().parsestr(archive.read(metadata_names[0]).decode())
        if metadata["Name"] != "opendoc-formats":
            raise ValueError("Expected OpenDoc Formats")
        version = metadata["Version"]
        expected_url = f"https://github.com/SergeiLitvinov/opendoc-formats/releases/download/v{version}/{wheel.name}"
        if source_url != expected_url or not wheel.name.startswith(f"opendoc_formats-{version}-"):
            raise ValueError("Expected the official release wheel URL and filename")
        if not any(
            re.fullmatch(r"opendoc-formats(?:\[[^\]]+\])?==" + re.escape(version), requirement)
            for requirement in consumer["project"]["dependencies"]
        ):
            raise ValueError("Pin the release version in pyproject.toml first")
        requirements = metadata.get_all("Requires-Dist", [])
        required_model = next((item for item in requirements if item.startswith("opendoc-model==")), None)
        if required_model not in consumer["project"]["dependencies"]:
            raise ValueError("Consumer must pin the same OpenDoc version as the adapters")
        files = {}
        modules = {}
        for name in archive.namelist():
            if ".." in Path(name).parts or "\\" in name or not name.startswith(("opendoc_formats/", "opendoc_formats-")):
                raise ValueError("Unexpected wheel path")
            if name.startswith("opendoc_formats/") and not name.endswith("/"):
                content = archive.read(name)
                files[name] = hashlib.sha256(content).hexdigest()
                if name.endswith(".py"):
                    modules[name] = files[name]
                    for node in ast.walk(ast.parse(content.decode())):
                        imports = (
                            [alias.name for alias in node.names]
                            if isinstance(node, ast.Import)
                            else [node.module or ""]
                            if isinstance(node, ast.ImportFrom)
                            else []
                        )
                        if any(item == "textalchemy" or item.startswith("textalchemy.") for item in imports):
                            raise ValueError("Library must not import its consumer")
        if not modules or "opendoc_formats/document_model.py" in files:
            raise ValueError("Expected independent adapters without a copied document model")
    bundle = ROOT / "vendor/opendoc-formats"
    target = bundle / wheel.name
    if (ROOT / consumer["tool"]["uv"]["sources"]["opendoc-formats"]["path"]).resolve() != target.resolve():
        raise ValueError("Pin the bundled wheel path first")
    previous = None
    provenance = bundle / "provenance.json"
    if provenance.is_file():
        old = json.loads(provenance.read_text(encoding="utf-8"))
        previous = bundle / old["wheel"]
        if previous.resolve().parent != bundle.resolve() or previous.suffix != ".whl":
            raise ValueError("Unsafe previous bundled wheel path")
        if hashlib.sha256(previous.read_bytes()).hexdigest() != old["sha256"]:
            raise ValueError("Previous bundled wheel checksum mismatch")
    if any(path not in (previous, target) for path in bundle.glob("*.whl")):
        raise ValueError("Unexpected bundled wheels; audit them before updating")
    manifest = {
        "distribution": "opendoc-formats",
        "version": version,
        "wheel": wheel.name,
        "sha256": digest,
        "modules": modules,
        "files": files,
        "source": {"url": source_url, "ref": source_ref, "checksum_verified": True},
        "scope": ["txt", "html", "docx", "epub", "pdf", "pptx", "djvu", "json", "latex", "exports", "fonts", "ooxml"],
    }
    bundle.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".whl.tmp")
    temporary.write_bytes(data)
    temporary.replace(target)
    provenance.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if previous is not None and previous != target:
        previous.unlink()
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-ref", required=True)
    args = parser.parse_args()
    print(update(args.wheel, sha256=args.sha256, source_url=args.source_url, source_ref=args.source_ref))
    subprocess.run(["uv", "lock", "--refresh-package", "opendoc-formats"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
