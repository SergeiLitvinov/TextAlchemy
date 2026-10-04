"""Enforce immutable library releases and the explicit consumer boundary."""

import ast
import hashlib
import importlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINES = frozenset(
    {"docx", "pptx", "fitz", "pymupdf", "pypdf", "lxml", "bs4", "ebooklib", "fontTools", "pdf2docx", "pdfplumber"}
)
MODEL_TYPES = frozenset(
    {
        "DocumentModel",
        "Paragraph",
        "TextRun",
        "Section",
        "Table",
        "TableCell",
        "TableRow",
        "Resource",
        "PackageGraph",
        "PackagePart",
        "PackageRelationship",
        "TextStyle",
        "Image",
        "Formula",
        "Box",
    }
)


def check_bundle(bundle: Path, package: Path) -> int:
    manifest = json.loads((bundle / "provenance.json").read_text(encoding="utf-8"))
    source = manifest.get("source", {})
    owner = manifest["distribution"]
    expected_url = f"https://github.com/SergeiLitvinov/{owner}/releases/download/v{manifest['version']}/{manifest['wheel']}"
    if source.get("url") != expected_url or source.get("checksum_verified") is not True:
        raise ValueError(f"{owner}: a checksum-verified published release is required")
    wheel = bundle / manifest["wheel"]
    if wheel.resolve().parent != bundle.resolve() or list(bundle.glob("*.whl")) != [wheel]:
        raise ValueError(f"{owner}: expected exactly one bundled wheel")
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError(f"{owner}: wheel checksum mismatch")
    files = manifest.get("files", manifest["modules"])
    with zipfile.ZipFile(wheel) as archive:
        for name, digest in files.items():
            relative = name.split("/", 1)[1]
            if ".." in Path(relative).parts or "\\" in relative:
                raise ValueError(f"{owner}: unsafe manifest path")
            installed = package / relative
            if (
                hashlib.sha256(archive.read(name)).hexdigest() != digest
                or hashlib.sha256(installed.read_bytes()).hexdigest() != digest
            ):
                raise ValueError(f"{owner}: installed code or resource differs from release: {relative}")
    return len(files)


def check_source_boundary(root: Path, contract: dict) -> tuple[int, int]:
    if contract.get("native_engine_bridges"):
        raise ValueError("Native engine exceptions are no longer allowed in the application")
    aliases = {}
    bridges = {}
    for path in (root / "src/textalchemy").rglob("*.py"):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "schemas.openxmlformats.org" in node.value or node.value.startswith(("word/", "/word/")):
                    raise ValueError(f"Native document structure belongs to OpenDoc Formats: {relative}")
            if isinstance(node, ast.ClassDef) and node.name in MODEL_TYPES:
                raise ValueError(f"Application must not define a copy of the document model: {relative}")
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                if name.startswith("opendoc_formats.native.") or name == "opendoc_formats.native":
                    raise ValueError(f"Private library import is not a stable contract: {relative}")
                if name == "xml" or name.startswith("xml."):
                    raise ValueError(f"Native document XML parsing belongs to OpenDoc Formats: {relative}")
                if name.split(".")[0] in ENGINES:
                    bridges.setdefault(relative, set()).add(name.split(".")[0])
            if (
                isinstance(node, ast.Call)
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and (
                    isinstance(node.func, ast.Name)
                    and node.func.id in {"import_module", "__import__"}
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                )
            ):
                dynamic_name = node.args[0].value
                if dynamic_name == "opendoc_formats.native" or dynamic_name.startswith("opendoc_formats.native."):
                    raise ValueError(f"Private library import is not a stable contract: {relative}")
                if dynamic_name == "xml" or dynamic_name.startswith("xml."):
                    raise ValueError(f"Native document XML parsing belongs to OpenDoc Formats: {relative}")
                if dynamic_name.split(".")[0] in ENGINES:
                    bridges.setdefault(relative, set()).add(dynamic_name.split(".")[0])
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "import_module"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.startswith("opendoc_formats.")
            ):
                aliases[relative] = node.args[0].value
        if relative in contract["compatibility_aliases"]:
            if any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in ast.walk(tree)):
                raise ValueError(f"Compatibility facade must not implement library behavior: {relative}")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "opendoc_formats":
                if any(alias.name == "native" for alias in node.names):
                    raise ValueError(f"Private library import is not a stable contract: {relative}")
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(("opendoc.", "opendoc_formats.")):
                if any(alias.name.startswith("_") for alias in node.names):
                    raise ValueError(f"Private library import is not a stable contract: {relative}")
    if aliases != contract["compatibility_aliases"]:
        raise ValueError("Compatibility facade inventory changed; audit the library contract first")
    expected = {key: set(value["engines"]) for key, value in contract["native_engine_bridges"].items()}
    if bridges != expected:
        raise ValueError("Native engine imports changed; use the library or create a separate library request")
    return len(aliases), len(bridges)


def main() -> None:
    contract = json.loads((ROOT / "contracts/libraries.json").read_text(encoding="utf-8"))
    counts = {}
    for name in ("opendoc", "opendoc-formats"):
        module = importlib.import_module(name.replace("-", "_"))
        package = Path(module.__file__).parent
        if package.resolve().is_relative_to((ROOT / "src").resolve()):
            raise ValueError("Libraries must be independently installed distributions")
        counts[name] = check_bundle(ROOT / "vendor" / name, package)
    aliases, bridges = check_source_boundary(ROOT, contract)
    for module_name, symbols in contract["public_api"].items():
        module = importlib.import_module(module_name)
        for name in symbols:
            if name.startswith("_") or not callable(getattr(module, name, None)):
                raise ValueError(f"Required public library API is unavailable: {module_name}.{name}")
    print(f"Published library files verified: {counts}; {aliases} facades; {bridges} native bridges; public APIs available")


if __name__ == "__main__":
    main()
