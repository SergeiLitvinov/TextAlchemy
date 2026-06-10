import hashlib
import re
from pathlib import Path
from typing import List, Set


def sanitize_filename(name: str, replacement: str = "_") -> str:
    name = re.sub(r'[<>:"/\\|?*]', replacement, name)
    name = re.sub(rf"[{re.escape(replacement)}]+", replacement, name)
    return name.strip(replacement)


def compute_file_hash(path: str | Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def find_duplicates(paths: List[str | Path]) -> List[Set[Path]]:
    from collections import defaultdict

    hash_map = defaultdict(list)
    for p in paths:
        p = Path(p)
        if p.is_file():
            hash_map[compute_file_hash(p)].append(p)

    return [set(group) for group in hash_map.values() if len(group) > 1]


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_text_file(path: str | Path) -> str:
    path = Path(path)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1251")


def write_text_file(path: str | Path, content: str) -> None:
    Path(path).write_text(content, encoding="utf-8")
