"""Повтор сохранённых файлов пакета с проверкой актуального состояния."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from textalchemy.convert.executor import ConversionExecutor
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.types import DocFormat
from textalchemy.web.services.batch_actions import parse_retry_selection
from textalchemy.web.services.conversion_catalog import web_plan_supported
from textalchemy.web.tasks import TaskStore

POLICY_FIELDS = (
    "max_loss_issues",
    "max_lost_objects",
    "require_unchanged_text",
    "text_preservation",
    "max_text_edits",
    "max_changed_formulas",
    "max_changed_emphasis",
)


def submit_saved_tasks(store: TaskStore, task_ids: list[str], *, resume: Callable[[str], None]) -> list[str]:
    """Отказ очереди оставляет сохранённую задачу ожидающей восстановления."""
    launched = []
    for task_id in task_ids:
        try:
            resume(task_id)
            launched.append(task_id)
        except RuntimeError as error:
            try:
                store.note_queue_failure(task_id, str(error))
            except OSError:
                # Исходник и queued-состояние уже сохранены: отказ пояснения не отменяет пакет.
                pass
    return launched


def retry_saved_task(store: TaskStore, task_id: str, *, resume: Callable[[str], None]) -> dict[str, Any]:
    """Повтор отдельного файла использует ту же проверку состояния и обработку очереди."""
    task = store.get(task_id)
    if task is None or store.source_path(task_id) is None:
        raise KeyError(task_id)
    if task.get("queue_kind") != "convert":
        raise ValueError("Для этого типа задачи повтор пока недоступен")
    if task.get("status") in {"queued", "running", "cancelling"}:
        raise ValueError("Задача уже выполняется")
    if not store.prepare_retry(
        task_id,
        expected=task,
        updates={
            "status": "queued",
            "error": None,
            "report": None,
            "artifact": None,
            "filename": task.get("source_name") or task.get("filename"),
        },
    ):
        raise ValueError("Состояние задачи изменилось; обновите список")
    submit_saved_tasks(store, [task_id], resume=resume)
    return {"task_id": task_id, "status": "queued"}


@dataclass(frozen=True)
class BatchRetryService:
    """Повтор выбранных сохранённых файлов с отчётом о причинах пропуска."""

    store: TaskStore
    resume: Callable[[str], None]
    executor_factory: Callable[[], ConversionExecutor] = ConversionExecutor

    def rerun(self, job_id: str, *, failed_only: bool = False, task_ids: str | None = None) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise LookupError("Job not found")
        selected = parse_retry_selection(task_ids, job)
        failed_only = failed_only or selected is not None
        executor = self.executor_factory()
        submissions, skipped = [], []
        for item in job.get("files", []):
            task_id = item["task_id"]
            if selected is not None and task_id not in selected:
                continue
            task = self.store.get(task_id) or {}
            reason = self._skip_reason(task_id, task, failed_only)
            if reason is None:
                updates = self._updates(item, task, job, executor)
                if updates is None:
                    reason = "Маршрут недоступен"
                else:
                    reason = self._prepare(task_id, task, updates)
            if reason is not None:
                skipped.append({"task_id": task_id, "name": item["name"], "reason": reason})
            else:
                submissions.append(task_id)
        launched = submit_saved_tasks(self.store, submissions, resume=self.resume)
        return {
            "success": True,
            "job_id": job_id,
            "launched": launched,
            "failed_only": failed_only,
            "queued": submissions,
            "skipped": skipped,
        }

    def _prepare(self, task_id: str, task: dict[str, Any], updates: dict[str, Any]) -> str | None:
        try:
            if not self.store.prepare_retry(task_id, expected=task, updates=updates):
                return "Состояние изменилось; обновите пакет"
        except OSError:
            return "Не удалось сохранить повтор; прежний результат сохранён. Повторите позже."
        return None

    def _skip_reason(self, task_id: str, task: dict[str, Any], failed_only: bool) -> str | None:
        if failed_only and task.get("status") not in {"error", "interrupted", "cancelled"}:
            return "Статус изменился или задача истекла"
        if self.store.source_path(task_id) is None:
            return "Исходный файл недоступен"
        if task.get("status") in {"queued", "running", "cancelling"}:
            return "Файл уже обрабатывается"
        return None

    def _updates(
        self, item: dict[str, Any], task: dict[str, Any], job: dict[str, Any], executor: ConversionExecutor
    ) -> dict[str, Any] | None:
        try:
            fallback_mode = ConversionMode(job.get("mode", "balanced"))
        except ValueError:
            fallback_mode = ConversionMode.BALANCED
        try:
            source, target = DocFormat(item["source_format"]), DocFormat(item["target_format"])
            mode = ConversionMode(task.get("mode", item.get("mode", fallback_mode.value)))
        except (KeyError, ValueError):
            return None
        plan = executor.plan(source, target, mode=mode)
        if plan is None or not web_plan_supported(plan):
            return None
        return {
            "status": "queued",
            "queue_kind": "convert",
            "error": None,
            "report": None,
            "artifact": None,
            **{
                field: task.get(field, job.get(field, False if field == "require_unchanged_text" else None))
                for field in POLICY_FIELDS
            },
            "source_format": source.value,
            "target_format": target.value,
            "mode": mode.value,
        }
