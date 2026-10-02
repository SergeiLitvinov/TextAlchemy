"""Чтение встроенного сайта без MkDocs, checkout проекта и распаковки файлов."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

DOCUMENTATION_BUNDLE = Path(__file__).resolve().parents[1] / "assets/documentation.zip"


@dataclass(frozen=True)
class DocumentationAsset:
    content: bytes
    media_type: str
    directory: bool = False


@dataclass(frozen=True)
class DocumentationService:
    """Доступны только записи поставленного комплекта; пользовательские файлы не читаются."""

    bundle: Path = DOCUMENTATION_BUNDLE

    def read(self, path: str) -> DocumentationAsset:
        if "\\" in path or "\x00" in path or path.startswith("/") or ".." in PurePosixPath(path).parts:
            raise LookupError("Страница документации не найдена")
        name = path or "index.html"
        if name.endswith("/"):
            name += "index.html"
        with ZipFile(self.bundle) as archive:
            directory = False
            if name not in archive.namelist() and not PurePosixPath(name).suffix:
                name += "/index.html"
                directory = True
            try:
                content = archive.read(name)
            except KeyError as error:
                raise LookupError("Страница документации не найдена") from error
        media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return DocumentationAsset(content, media_type, directory)
