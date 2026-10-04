"""Compatibility imports; document implementation lives in opendoc."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opendoc import document_codec as _codec
from opendoc.document_codec import (
    FORMAT_VERSION as FORMAT_VERSION,
)
from opendoc.document_codec import (
    SUPPORTED_FORMAT_VERSIONS as SUPPORTED_FORMAT_VERSIONS,
)
from opendoc.document_model import DocumentModel

FORMAT_NAME = _codec.FORMAT_NAME
LEGACY_FORMAT_NAME = "textalchemy.document"


def document_to_dict(document: DocumentModel) -> dict[str, Any]:
    """Записать стандарт OpenDoc для чтения независимыми потребителями."""
    return _codec.document_to_dict(document)


def document_from_dict(payload: dict[str, Any]) -> DocumentModel:
    """Прочитать файлы приложения и OpenDoc без изменения исходного словаря."""
    legacy = payload.get("format") == LEGACY_FORMAT_NAME and payload.get("version") == 1
    if payload.get("format") == LEGACY_FORMAT_NAME:
        payload = {**payload, "format": _codec.FORMAT_NAME}
    document = _codec.document_from_dict(payload)
    if legacy:
        from textalchemy.core.legacy_document import migrate_legacy_ooxml_resources

        document = migrate_legacy_ooxml_resources(document)
        errors = document.validate()
        if errors:
            raise ValueError("invalid legacy document model: " + "; ".join(errors))
    return document


def document_to_json(document: DocumentModel, *, indent: int | None = None) -> str:
    return json.dumps(document_to_dict(document), ensure_ascii=False, indent=indent)


def document_from_json(value: str | bytes) -> DocumentModel:
    return document_from_dict(json.loads(value))


def save_document(document: DocumentModel, path: str | Path, *, indent: int | None = 2) -> Path:
    from textalchemy.core.io import atomic_write_text

    return atomic_write_text(path, document_to_json(document, indent=indent), encoding="utf-8")


def load_document(path: str | Path) -> DocumentModel:
    return document_from_json(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "document_from_dict",
    "document_from_json",
    "document_to_dict",
    "document_to_json",
    "load_document",
    "save_document",
]
