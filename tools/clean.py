"""Preview or remove only known reproducible project caches (never application data)."""

import argparse
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED = (".pytest_cache", ".ruff_cache", ".mypy_cache", ".coverage", "coverage.xml", "htmlcov", "build", "dist",
         ".codex-web-err.log", ".codex-web-out.log")


def linked(path):
    if path.is_symlink():
        return True
    return os.name == "nt" and bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def safe_tree(path, root):
    """Validate the complete tree before recursive removal, including Windows junctions."""
    if not path.resolve().is_relative_to(root.resolve()) or path.resolve() == root.resolve():
        raise ValueError(f"Outside cleanup scope: {path}")
    for parent in (path, *path.parents):
        if parent == root:
            break
        if linked(parent):
            raise ValueError(f"Linked path is not disposable: {path}")
    if path.is_dir():
        for directory, folders, files in os.walk(path, followlinks=False):
            if ".git" in folders or ".git" in files:
                raise ValueError(f"Embedded repository is not disposable: {path}")
            for name in folders + files:
                if linked(Path(directory) / name):
                    raise ValueError(f"Linked entry in cache: {path}")


def candidates(root, *, development_artifacts=False):
    paths = [root / name for name in FIXED if (root / name).exists()]
    for area in ("src", "tests", "tools"):
        for directory, folders, _ in os.walk(root / area, followlinks=False):
            folders[:] = [name for name in folders if not linked(Path(directory) / name)]
            if "__pycache__" in folders:
                paths.append(Path(directory) / "__pycache__")
                folders.remove("__pycache__")
    paths.extend(path for path in (root / "src").glob("*.egg-info") if path.is_dir())
    if development_artifacts:
        manifest = Path(__file__).with_name("cleanup-artifacts.json")
        for name in json.loads(manifest.read_text(encoding="utf-8")):
            if Path(name).name != name or name in (".", ".."):
                raise ValueError(f"Unsafe cleanup manifest entry: {name}")
            path = root / ".textalchemy" / name
            if path.exists():
                paths.append(path)
    return sorted(paths)


def clean(root=ROOT, *, apply=False, development_artifacts=False):
    root = root.resolve()
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True)
    tracked = listing.stdout.decode("utf-8").split("\0")
    paths = candidates(root, development_artifacts=development_artifacts)
    # Preflight every candidate before deleting any of them.
    for path in paths:
        safe_tree(path, root)
        relative = path.relative_to(root).as_posix()
        if any(name == relative or name.startswith(relative + "/") for name in tracked):
            raise ValueError(f"Tracked files in cleanup candidate: {relative}")
    sizes = []
    for path in paths:
        size = sum(file.stat().st_size for file in path.rglob("*") if file.is_file()) if path.is_dir() else path.stat().st_size
        sizes.append({"path": path.relative_to(root).as_posix(), "bytes": size})
        if apply:
            safe_tree(path, root)
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    return {"applied": apply, "bytes": sum(item["bytes"] for item in sizes), "items": sizes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Remove the listed caches; otherwise preview only")
    parser.add_argument(
        "--development-artifacts", action="store_true", help="Also include explicitly listed old development artifacts"
    )
    args = parser.parse_args()
    print(json.dumps(clean(apply=args.apply, development_artifacts=args.development_artifacts), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
