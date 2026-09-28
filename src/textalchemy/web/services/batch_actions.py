"""Массовые действия пакета с сохранением завершённых результатов."""

from __future__ import annotations

import json
from typing import Any, Callable

from textalchemy.web.tasks import TaskStore


def parse_retry_selection(raw: str | None, job: dict[str, Any]) -> set[str] | None:
    """Проверить явный выбор целиком до изменения любой задачи пакета."""
    if raw is None:
        return None
    try:
        values = json.loads(raw)
    except ValueError as error:
        raise ValueError("Выбор файлов должен быть JSON-списком идентификаторов") from error
    if not isinstance(values, list) or not values or any(not isinstance(value, str) for value in values):
        raise ValueError("Выберите хотя бы один файл пакета")
    known = {item["task_id"] for item in job.get("files", [])}
    if len(values) != len(set(values)) or not set(values) <= known:
        raise ValueError("Выбор содержит повторяющиеся или чужие файлы. Обновите пакет.")
    return set(values)


def cancel_batch(store: TaskStore, job_id: str, *, cancel_task: Callable[[str], dict[str, Any]],
                 task_ids: str | None = None) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise LookupError("Пакет не найден или срок хранения истёк")
    selected = parse_retry_selection(task_ids, job)
    requested, skipped = [], []
    for item in job.get("files", []):
        task_id = item["task_id"]
        if selected is not None and task_id not in selected:
            continue
        task = store.get(task_id)
        if task is None or task.get("status") not in {"queued", "running"}:
            skipped.append(task_id)
            continue
        try:
            requested.append(cancel_task(task_id))
        except (KeyError, ValueError):
            skipped.append(task_id)
    return {"success": True, "job_id": job_id, "requested": requested, "skipped": skipped}
