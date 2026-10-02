"""Публичная история пакетов и их задач без HTTP-обработчиков."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from textalchemy.web.tasks import TaskStore


@dataclass(frozen=True)
class BatchHistoryService:
    store: TaskStore
    public_task: Callable[[dict[str, Any]], dict[str, Any]]

    def list(self, *, limit: int = 20) -> dict[str, Any]:
        result = []
        for job in self.store.list_jobs(limit=limit):
            files = job.get("files", [])
            counts = dict.fromkeys(("queued", "running", "done", "error", "expired", "interrupted"), 0)
            for item in files:
                task = self.store.get(item["task_id"])
                status = task["status"] if task else "expired"
                counts[status] = counts.get(status, 0) + 1
            result.append(
                {
                    "job_id": job["job_id"],
                    "created": job.get("_ts"),
                    "target_format": job.get("target_format"),
                    "mode": job.get("mode"),
                    "files": [item["name"] for item in files],
                    "counts": counts,
                }
            )
        return {"jobs": result}

    def get(self, job_id: str) -> dict[str, Any]:
        job = self._job(job_id)
        entries = []
        for item in job.get("files", []):
            task = self.store.get(item["task_id"])
            entry = {
                "name": item["name"],
                "task_id": item["task_id"],
                "target_format": item.get("target_format"),
                "mode": item.get("mode", job.get("mode")),
                "status_url": item.get("status"),
                "result_url": item.get("result"),
            }
            entry.update(
                self.public_task(task) if task is not None else {"status": "expired", "error": "Истёк срок хранения результата"}
            )
            entries.append(entry)
        return {"job_id": job_id, "target_format": job.get("target_format"), "mode": job.get("mode"), "tasks": entries}

    def delete(self, job_id: str) -> dict[str, Any]:
        job = self._job(job_id)
        for item in job.get("files", []):
            self.store.delete(item["task_id"])
        self.store.delete_job(job_id)
        return {"success": True, "job_id": job_id}

    def _job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise LookupError("Job not found")
        return job
