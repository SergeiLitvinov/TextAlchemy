import hashlib
import re
import zipfile
from pathlib import Path
from typing import List, Optional


def progress_bar(current: int, total: int, width: int = 30) -> str:
    filled = int(width * current / total) if total > 0 else 0
    bar = "#" * filled + "." * (width - filled)
    return f"[{bar}] {current}/{total}"


def calculate_file_hash(file_path: Path, algorithm: str = "md5") -> str:
    h = hashlib.new(algorithm)
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def find_duplicates(folder: Path) -> dict:
    hashes: dict[str, Path] = {}
    duplicates: dict[Path, list[Path]] = {}
    for file in folder.rglob("*"):
        if not file.is_file():
            continue
        file_hash = calculate_file_hash(file)
        if file_hash in hashes:
            if hashes[file_hash] not in duplicates:
                duplicates[hashes[file_hash]] = []
            duplicates[hashes[file_hash]].append(file)
        else:
            hashes[file_hash] = file
    return duplicates


def validate_pdf(file_path: Path) -> bool:
    try:
        import pypdf
        with open(file_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            _ = len(reader.pages)
        return True
    except Exception:
        return False


def get_file_info(file_path: Path) -> dict:
    stat = file_path.stat()
    return {
        "name": file_path.name,
        "path": str(file_path),
        "size": stat.st_size,
        "size_mb": round(stat.st_size / 1024 / 1024, 2),
        "modified": stat.st_mtime,
        "extension": file_path.suffix.lower(),
    }


def list_files(folder: Path, extensions: Optional[List[str]] = None, recursive: bool = False) -> List[dict]:
    files = []
    pattern = "**/*" if recursive else "*"
    for file in folder.glob(pattern):
        if not file.is_file():
            continue
        if extensions and file.suffix.lower() not in extensions:
            continue
        files.append(get_file_info(file))
    return sorted(files, key=lambda x: x["name"])


def create_zip_archive(files: List[Path], output_path: Path) -> Path:
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in files:
            zf.write(file, file.name)
    return output_path


def sanitize_path(path: str) -> str:
    path = re.sub(r'[<>:"/\\|?*]', "_", path)
    path = re.sub(r"_+", "_", path)
    return path.strip("_")


def ensure_folder(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_file_content(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        from textalchemy.organize.extractors.pdf import read_pdf
        return read_pdf(str(file_path))
    elif ext == ".docx":
        from textalchemy.organize.extractors.docx import read_docx
        return read_docx(str(file_path))
    elif ext in (".txt", ".doc"):
        from textalchemy.organize.extractors.txt import read_txt
        return read_txt(str(file_path))
    elif ext == ".djvu":
        from textalchemy.organize.extractors.txt import read_djvu
        return read_djvu(str(file_path))
    return ""
