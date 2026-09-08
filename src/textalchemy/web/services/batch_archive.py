"""Сборка готовых результатов пакета в ограниченный по размеру временный ZIP."""

from __future__ import annotations

import json
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
from zipfile import ZIP_STORED, ZipFile

from textalchemy.core.artifacts import safe_artifact_filename
from textalchemy.web.tasks import TaskStore

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
ACTIVE_STATES = {"queued", "running", "cancelling"}


def build_batch_archive(store: TaskStore, job_id: str, *, max_bytes: int = MAX_ARCHIVE_BYTES) -> BinaryIO:
    job = store.get_job(job_id)
    if job is None:
        raise LookupError("Пакет не найден или срок хранения истёк")
    entries = [(item, store.get(item["task_id"])) for item in job.get("files", [])]
    if any(task and task.get("status") in ACTIVE_STATES for _, task in entries):
        raise ValueError("Дождитесь завершения всех файлов пакета")
    stream = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    try:
        _write_archive(stream, store, entries, max_bytes)
        stream.seek(0)
        return stream
    except BaseException:
        stream.close()
        raise


def _write_archive(stream: BinaryIO, store: TaskStore, entries: list, max_bytes: int) -> None:
    manifest, total, included = [], 0, 0
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        for index, (item, task) in enumerate(entries, 1):
            status = task.get("status", "unknown") if task else "expired"
            record = {"name": item["name"], "status": status, "file": None}
            path = store.result_path(item["task_id"], task["artifact"]) if status == "done" and task.get("artifact") else None
            if status == "done" and path is None:
                record["status"] = "unavailable"
            if path is not None:
                name = f"{index:02d}/" + safe_artifact_filename(path.name, fallback="result")
                with path.open("rb") as source, archive.open(name, "w") as destination:
                    while chunk := source.read(1024 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise OverflowError("Результаты превышают лимит ZIP 512 МБ. Скачайте файлы по отдельности.")
                        destination.write(chunk)
                record["file"] = name
                included += 1
            manifest.append(record)
        if not included:
            raise ValueError("В пакете нет доступных готовых результатов")
        archive.writestr("manifest.json", json.dumps({"files": manifest}, ensure_ascii=False, indent=2).encode("utf-8"))
