"""Application projection for the global task and storage center."""

from __future__ import annotations

import time
from typing import Any, Callable

from textalchemy.web.tasks import TaskStore

_ACTIVE = {"queued", "running", "cancelling"}


class TaskCenterService:
    def __init__(
        self,
        store: TaskStore,
        *,
        cancel_task: Callable[[str], dict[str, Any]] | None = None,
        rerun_task: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self._store = store
        self._cancel_task = cancel_task
        self._rerun_task = rerun_task

    def snapshot(self, *, limit: int = 12) -> dict[str, Any]:
        visible = [task for task in self._store.list_tasks(limit=None) if task.get('queue_kind') != 'pipeline-input']
        tasks = [self._public_task(task) for task in visible[:limit]]
        counts: dict[str, int] = {}
        for task in tasks:
            status = str(task["status"])
            counts[status] = counts.get(status, 0) + 1
        return {
            "tasks": tasks,
            "counts": counts,
            "active": sum(counts.get(status, 0) for status in _ACTIVE),
            "retention_seconds": self._store.ttl_seconds,
            "storage": {
                "scope": "local-device",
                "root_label": "каталог данных TextAlchemy",
                "bytes": self._store.storage_bytes(),
                "automatic_cleanup": True,
                "external_uploads": False,
            },
        }

    def clear_finished(self) -> int:
        removed = 0
        for task in self._store.list_tasks(limit=None):
            if task.get("status") in _ACTIVE or task.get('queue_kind') == 'pipeline-input':
                continue
            self._store.delete(str(task["task_id"]))
            removed += 1
        return removed

    def cancel(self, task_id: str) -> dict[str, Any]:
        if self._cancel_task is None:
            raise ValueError("Отмена задач не настроена")
        return self._cancel_task(task_id)

    def rerun(self, task_id: str) -> dict[str, Any]:
        if self._rerun_task is None:
            raise ValueError("Повтор задач не настроен")
        return self._rerun_task(task_id)

    @staticmethod
    def _public_task(task: dict[str, Any]) -> dict[str, Any]:
        timestamp = task.get("_ts")
        age_seconds = max(0, round(time.time() - timestamp)) if isinstance(timestamp, (int, float)) else None
        prefix = {'generate-preview': '/api/generate/results/', 'pipeline-result': '/api/pipeline/results/'}.get(
            task.get('queue_kind'), '/api/convert/result/')
        return {
            "task_id": task.get("task_id"),
            "status": task.get("status", "unknown"),
            "filename": task.get("filename") or task.get("source_name") or "Документ",
            "source_format": task.get("source_format"),
            "target_format": task.get("target_format"),
            "mode": task.get("mode"),
            "error": task.get("error"),
            "age_seconds": age_seconds,
            "result_url": (
                prefix + task['task_id']
                if task.get("status") == "done" and task.get("artifact") and task.get("task_id")
                else None
            ),
            "can_cancel": task.get("status") in {"queued", "running"},
            "can_rerun": task.get("queue_kind") == "convert" and task.get("status") not in _ACTIVE,
        }


__all__ = ["TaskCenterService"]
