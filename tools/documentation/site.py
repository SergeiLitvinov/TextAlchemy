"""Assemble only documented files into a disposable MkDocs source tree."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

from tools.documentation.generated import ROOT

STAGE = ROOT / ".textalchemy/docs-source"
SNAPSHOTS = {"todo-2026-09-13.md", "todo-before-milestones-2026-09-13.md"}


def write_changed(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def prepare():
    docs = sorted([*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md"), *(ROOT / "tests/corpus").rglob("README.md")])
    contents = {path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8") for path in docs}
    # A fresh interpreter sees edited CLI/operation modules during live rebuilds.
    reference = subprocess.run(
        [sys.executable, "-m", "tools.documentation.generated"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    contents.update(json.loads(reference.stdout))
    assets = {}
    outputs = {}
    for name, content in contents.items():
        if Path(name).name in SNAPSHOTS:
            # Frozen snapshots retain original paths. Show as evidence, not live guidance.
            assets[name + ".txt"] = (ROOT / name).read_bytes()
            content = (
                "# Архив: " + Path(name).stem + "\n\n"
                "Исторический снимок, не текущие инструкции. [Скачать исходник](" + Path(name).name + ".txt).\n\n"
                "````text\n" + content + "\n````\n"
            )
        else:
            content = rewrite_links(content, name, contents, assets)
        outputs[name] = content.encode("utf-8")
    for path in (ROOT / "docs/examples").iterdir():
        if path.is_file():
            assets[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for path in (ROOT / "docs/assets").rglob("*"):
        if path.is_file():
            assets[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    outputs.update(assets)
    STAGE.mkdir(parents=True, exist_ok=True)
    if STAGE.resolve() != (ROOT.resolve() / ".textalchemy/docs-source"):
        raise ValueError("Unexpected docs staging path")
    for file in STAGE.rglob("*"):
        if file.is_file() and file.relative_to(STAGE).as_posix() not in outputs:
            file.unlink()
    for name, data in outputs.items():
        write_changed(STAGE / name, data)
    return len(contents)


def rewrite_links(content, name, contents, assets):
    def replace(match):
        url = match[1]
        if re.match(r"[a-zA-Z]+://|mailto:", url) or url.startswith("#"):
            return match[0]
        path, _, fragment = unquote(url).partition("#")
        target = ((ROOT / name).parent / path).resolve()
        if not target.is_relative_to(ROOT.resolve()) or not target.is_file():
            raise ValueError(f"{name}: invalid local link {url}")
        relative = target.relative_to(ROOT).as_posix()
        if relative in contents:
            destination = relative
        elif relative.startswith("docs/examples/"):
            destination = relative
            assets[destination] = target.read_bytes()
        else:
            parts = ("dot-" + part[1:] if part.startswith(".") else part for part in Path(relative).parts)
            destination = "files/" + "/".join(parts)
            assets[destination] = target.read_bytes()
        new = Path(os.path.relpath(destination, Path(name).parent)).as_posix()
        return "](" + new + ("#" + fragment if fragment else "") + ")"

    pieces = re.split(r"(^```.*?^```[^\n]*)", content, flags=re.M | re.S)
    return "".join(piece if index % 2 else re.sub(r"\]\(([^)]+)\)", replace, piece) for index, piece in enumerate(pieces))
