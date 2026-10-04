"""Select and update an application release version without touching library versions."""

import argparse
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:(a|b|rc)([1-9]\d*))?")


def current(root: Path = ROOT) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def select(selector: str, installed: str) -> str:
    match = VERSION.fullmatch(installed)
    if not match:
        raise ValueError("Invalid current application version")
    if selector == "current":
        return installed
    if selector in {"patch", "minor", "major"}:
        parts = [int(match[index]) for index in (1, 2, 3)]
        position = {"major": 0, "minor": 1, "patch": 2}[selector]
        parts[position] += 1
        parts[position + 1:] = [0] * (2 - position)
        return ".".join(map(str, parts))
    if not VERSION.fullmatch(selector):
        raise ValueError("Expected current, patch, minor, major or a three-component version (optionally a/b/rc)")
    # CI may promote a candidate to its stable version, but must not go backwards.
    def order(version: str) -> tuple:
        item = VERSION.fullmatch(version)
        return (*(int(item[index]) for index in (1, 2, 3)), {"a": 0, "b": 1, "rc": 2, None: 3}[item[4]],
                int(item[5] or 0))
    if order(selector) < order(installed):
        raise ValueError("Release versions must not go backwards")
    return selector


def set_version(version: str, root: Path = ROOT) -> None:
    previous = current(root)
    select(version, previous)
    paths = ["pyproject.toml", "uv.lock", "README.md", "doc/development/releases.md"]
    pending = {}
    for name in paths:
        text = (root / name).read_text(encoding="utf-8")
        if name == "pyproject.toml":
            updated, count = re.subn(r'(?m)^version = "' + re.escape(previous) + r'"$', f'version = "{version}"', text)
        elif name == "uv.lock":
            updated, count = re.subn(r'(\[\[package\]\]\nname = "textalchemy"\nversion = ")[^"]+("\n)',
                                     lambda match: match[1] + version + match[2], text)
        else:
            count = text.count(previous)
            updated = text.replace(previous, version)
        if not count or (name in {"pyproject.toml", "uv.lock"} and count != 1):
            raise ValueError(f"Cannot update release version in {name}")
        pending[name] = updated
    for name, text in pending.items():
        (root / name).write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "set"])
    parser.add_argument("version", help="current, patch, minor, major or an explicit version")
    args = parser.parse_args()
    version = select(args.version, current())
    if args.action == "set":
        set_version(version)
    print(version)


if __name__ == "__main__":
    main()
