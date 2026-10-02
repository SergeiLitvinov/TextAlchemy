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
from opendoc.document_codec import (
    _block_from_dict as _block_from_dict,
)
from opendoc.document_codec import (
    _block_to_dict as _block_to_dict,
)
from opendoc.document_codec import (
    _box_from_dict as _box_from_dict,
)
from opendoc.document_codec import (
    _box_to_dict as _box_to_dict,
)
from opendoc.document_codec import (
    _color_from_value as _color_from_value,
)
from opendoc.document_codec import (
    _color_to_value as _color_to_value,
)
from opendoc.document_codec import (
    _crop_from_dict as _crop_from_dict,
)
from opendoc.document_codec import (
    _crop_to_dict as _crop_to_dict,
)
from opendoc.document_codec import (
    _inline_from_dict as _inline_from_dict,
)
from opendoc.document_codec import (
    _inline_to_dict as _inline_to_dict,
)
from opendoc.document_codec import (
    _length_from_value as _length_from_value,
)
from opendoc.document_codec import (
    _length_to_value as _length_to_value,
)
from opendoc.document_codec import (
    _migrate_legacy_package_resources as _migrate_legacy_package_resources,
)
from opendoc.document_codec import (
    _package_from_dict as _package_from_dict,
)
from opendoc.document_codec import (
    _package_to_dict as _package_to_dict,
)
from opendoc.document_codec import (
    _page_from_dict as _page_from_dict,
)
from opendoc.document_codec import (
    _page_to_dict as _page_to_dict,
)
from opendoc.document_codec import (
    _properties_to_dict as _properties_to_dict,
)
from opendoc.document_codec import (
    _provenance_from_dict as _provenance_from_dict,
)
from opendoc.document_codec import (
    _provenance_to_dict as _provenance_to_dict,
)
from opendoc.document_codec import (
    _resource_from_dict as _resource_from_dict,
)
from opendoc.document_codec import (
    _resource_to_dict as _resource_to_dict,
)
from opendoc.document_codec import (
    _section_from_dict as _section_from_dict,
)
from opendoc.document_codec import (
    _section_to_dict as _section_to_dict,
)
from opendoc.document_codec import (
    _style_from_dict as _style_from_dict,
)
from opendoc.document_codec import (
    _style_to_dict as _style_to_dict,
)
from opendoc.document_codec import (
    _surrogate_from_dict as _surrogate_from_dict,
)
from opendoc.document_codec import (
    _surrogate_to_dict as _surrogate_to_dict,
)
from opendoc.document_model import DocumentModel

FORMAT_NAME = "textalchemy.document"


def document_to_dict(document: DocumentModel) -> dict[str, Any]:
    """Сохранить прежний идентификатор файлов приложения поверх модели OpenDoc."""
    payload = _codec.document_to_dict(document)
    payload["format"] = FORMAT_NAME
    return payload


def document_from_dict(payload: dict[str, Any]) -> DocumentModel:
    """Прочитать файлы приложения и OpenDoc без изменения исходного словаря."""
    if payload.get("format") == FORMAT_NAME:
        payload = {**payload, "format": _codec.FORMAT_NAME}
    return _codec.document_from_dict(payload)


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
