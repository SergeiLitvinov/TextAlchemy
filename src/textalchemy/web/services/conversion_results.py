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


def inspect_task_source(task, source_path: Path, source: DocFormat, inspector):
    """Inspect with the saved text profile; failure must not prevent conversion."""
    try:
        if task.get("txt_encoding", "auto") != "auto" and source is DocFormat.TXT:
            from textalchemy.convert.library_import import inspect_source

            inspection = inspect_source(source_path, task["txt_encoding"])
        else:
            inspection = inspector(source_path)
        return inspection, None
    except Exception as error:  # noqa: BLE001 - unsupported inspection is nonfatal
        return None, f"Не удалось проверить исходный документ: {error}"
