"""Единый набор файловых утилит.

Заменяет две ранее существовавшие копии:
  - ``core/file_utils.py`` (sha256, list-путей, sanitize_filename)
  - ``organize/utils.py``     (md5, folder-scan, sanitize_path, zip, file_info)

Поведение каждой функции зафиксировано; старые модули — re-export.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional, Union

PathLike = Union[str, Path]

DEFAULT_MAX_ARCHIVE_ENTRIES = 100_000
DEFAULT_MAX_ARCHIVE_SIZE = 512 * 1024 * 1024
DEFAULT_MAX_COMPRESSION_RATIO = 200


class ArchiveSafetyError(ValueError):
    """Архив нарушает лимиты безопасности (zip-бомба, path traversal и т.п.)."""


def check_archive_safety(
    path: PathLike,
    *,
    max_entries: int = DEFAULT_MAX_ARCHIVE_ENTRIES,
    max_total_size: int = DEFAULT_MAX_ARCHIVE_SIZE,
    max_ratio: int = DEFAULT_MAX_COMPRESSION_RATIO,
) -> None:
    """Проверить zip/OOXML/EPUB перед распаковкой; поднимает ``ArchiveSafetyError``.

    Читает только центральный каталог (без извлечения данных) и проверяет:
      * число записей и суммарный размер не превышают лимиты;
      * коэффициент сжатия не указывает на zip-бомбу;
      * имена записей безопасны для извлечения: без ``..``, абсолютных путей
        и дубликатов (защита от path traversal / zip-slip).
    """
    p = Path(path)
    try:
        with zipfile.ZipFile(p) as zf:
            infos = zf.infolist()
            if len(infos) > max_entries:
                raise ArchiveSafetyError(
                    f"Слишком много записей в архиве: {len(infos)} > {max_entries}"
                )
            total_size = 0
            total_compressed = 0
            seen: set[str] = set()
            for info in infos:
                name = info.filename
                if name in seen:
                    raise ArchiveSafetyError(f"Дубликат записи в архиве: {name}")
                seen.add(name)
                normalized = name.replace("\\", "/")
                if normalized.startswith(("/", "//")):
                    raise ArchiveSafetyError(f"Абсолютный путь в архиве: {name}")
                if re.match(r"^[a-zA-Z]:", normalized):
                    raise ArchiveSafetyError(f"Путь с буквой диска в архиве: {name}")
                if any(part == ".." for part in normalized.split("/")):
                    raise ArchiveSafetyError(f"Path traversal в архиве: {name}")
                if info.file_size > max_total_size:
                    raise ArchiveSafetyError(f"Запись слишком большая: {name} {info.file_size} байт")
                total_size += info.file_size
                total_compressed += info.compress_size
            if total_size > max_total_size:
                raise ArchiveSafetyError(f"Суммарный размер архива превышает лимит: {total_size} байт")
            if total_compressed > 0 and total_size > total_compressed * max_ratio:
                raise ArchiveSafetyError(
                    f"Подозрительный коэффициент сжатия: {total_size} / {total_compressed}"
                )
    except (zipfile.BadZipFile, OSError) as e:
        raise ArchiveSafetyError(f"Некорректный zip-архив: {e}") from e


def compute_hash(path: PathLike, algorithm: str = "sha256", chunk: int = 65536) -> str:
    """Хеш файла. ``FileNotFoundError`` если файла нет."""
    p = Path(path)
    h = hashlib.new(algorithm)
    with open(p, "rb") as f:
        for piece in iter(lambda: f.read(chunk), b""):
            h.update(piece)
    return h.hexdigest()


def find_duplicates_by_paths(paths: Iterable[PathLike]) -> list[set[Path]]:
    """Группировка дубликатов по списку путей: ``list[set[Path]]``."""
    hash_map: dict[str, list[Path]] = defaultdict(list)
    for p in paths:
        pp = Path(p)
        if pp.is_file():
            hash_map[compute_hash(pp)].append(pp)
    return [set(group) for group in hash_map.values() if len(group) > 1]


def find_duplicates_in_folder(folder: PathLike) -> dict[Path, list[Path]]:
    """Сканирует папку, возвращает ``{canonical: [duplicates...]}``."""
    folder = Path(folder)
    hashes: dict[str, Path] = {}
    duplicates: dict[Path, list[Path]] = {}
    for file in folder.rglob("*"):
        if not file.is_file():
            continue
        h = compute_hash(file)
        if h in hashes:
            if hashes[h] not in duplicates:
                duplicates[hashes[h]] = []
            duplicates[hashes[h]].append(file)
        else:
            hashes[h] = file
    return duplicates


def sanitize_filename(name: str, replacement: str = "_") -> str:
    """Убирает спец-символы, схлопывает повторы замены, обрезает по краям."""
    name = re.sub(r'[<>:"/\\|?*]', replacement, name)
    name = re.sub(rf"[{re.escape(replacement)}]+", replacement, name)
    return name.strip(replacement)


def sanitize_path(path: str) -> str:
    """Алиас без параметра replacement (для совместимости с organize.utils)."""
    return sanitize_filename(path, replacement="_")


def ensure_dir(path: PathLike) -> Path:
    """Создать директорию (с родителями); вернуть Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_folder(folder: PathLike) -> Path:
    """Алиас для совместимости с organize.utils."""
    return ensure_dir(folder)


def read_text_file(path: PathLike) -> str:
    """Прочитать текст: utf-8 → cp1251 fallback. ``FileNotFoundError`` если нет."""
    p = Path(path)
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="cp1251")


def write_text_file(path: PathLike, content: str) -> None:
    """Записать текст в utf-8."""
    Path(path).write_text(content, encoding="utf-8")


def progress_bar(current: int, total: int, width: int = 30) -> str:
    """ASCII-индикатор прогресса в строку."""
    filled = int(width * current / total) if total > 0 else 0
    bar = "#" * filled + "." * (width - filled)
    return f"[{bar}] {current}/{total}"


def validate_pdf(file_path: PathLike) -> bool:
    """Можно ли открыть файл как PDF (через pypdf)."""
    try:
        import pypdf
        with open(file_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            _ = len(reader.pages)
        return True
    except Exception:  # noqa: BLE001
        return False


def get_file_info(file_path: PathLike) -> dict:
    """Метаданные файла: name/path/size/size_mb/modified/extension."""
    p = Path(file_path)
    stat = p.stat()
    return {
        "name": p.name,
        "path": str(p),
        "size": stat.st_size,
        "size_mb": round(stat.st_size / 1024 / 1024, 2),
        "modified": stat.st_mtime,
        "extension": p.suffix.lower(),
    }


def list_files(
    folder: PathLike,
    extensions: Optional[list[str]] = None,
    recursive: bool = False,
) -> list[dict]:
    """Список файлов в директории с метаданными (отсортировано по имени)."""
    folder = Path(folder)
    pattern = "**/*" if recursive else "*"
    files: list[dict] = []
    for file in folder.glob(pattern):
        if not file.is_file():
            continue
        if extensions and file.suffix.lower() not in extensions:
            continue
        files.append(get_file_info(file))
    return sorted(files, key=lambda x: x["name"])


def create_zip_archive(files: list[Path], output_path: Path) -> Path:
    """Упаковать список файлов в zip."""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in files:
            zf.write(file, file.name)
    return output_path


__all__ = [
    "ArchiveSafetyError",
    "check_archive_safety",
    "compute_hash",
    "find_duplicates_by_paths",
    "find_duplicates_in_folder",
    "sanitize_filename",
    "sanitize_path",
    "ensure_dir",
    "ensure_folder",
    "read_text_file",
    "write_text_file",
    "progress_bar",
    "validate_pdf",
    "get_file_info",
    "list_files",
    "create_zip_archive",
]
