"""Публичные метаданные результата и инспекции конвертации."""

from pathlib import Path

from textalchemy.core.types import DocFormat
from textalchemy.web.services.conversion_catalog import MEDIA_TYPES


def inspection_payload(inspection, display_name: str) -> dict[str, object] | None:
    if inspection is None:
        return None
    payload = inspection.to_dict()
    payload["source_path"] = display_name
    return payload


def artifact_meta(output_path: Path, source_stem: str, target: DocFormat) -> tuple[str, str]:
    if output_path.is_dir():
        return f"{source_stem}-html", "application/zip"
    return output_path.name, MEDIA_TYPES[target]
