"""Массовые действия пакета с сохранением завершённых результатов."""

from __future__ import annotations

from typing import Any, Callable

from textalchemy.web.tasks import TaskStore


def cancel_batch(store: TaskStore, job_id: str, *, cancel_task: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise LookupError("Пакет не найден или срок хранения истёк")
    requested, skipped = [], []
    for item in job.get("files", []):
        task_id = item["task_id"]
        task = store.get(task_id)
        if task is None or task.get("status") not in {"queued", "running"}:
            skipped.append(task_id)
            continue
        try:
            requested.append(cancel_task(task_id))
        except (KeyError, ValueError):
            skipped.append(task_id)
    return {"success": True, "job_id": job_id, "requested": requested, "skipped": skipped}
