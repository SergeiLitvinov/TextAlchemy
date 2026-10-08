"""Жизненный цикл сохранённой задачи конвертации вне HTTP-слоя."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from typing import Any, Callable

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.inspection import compare_inspections, inspect_path
from textalchemy.core.object_quality_policy import ObjectLossPolicy
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.types import DocFormat
from textalchemy.web.queue import TaskQueue
from textalchemy.web.services.batch_retry import retry_saved_task
from textalchemy.web.services.conversion_catalog import output_path_for
from textalchemy.web.services.conversion_policy import request_policy_fields, stored_policy_fields
from textalchemy.web.services.conversion_results import artifact_meta, inspect_task_source, inspection_payload
from textalchemy.web.tasks import TaskStore


class ConversionTaskService:
    """Сохраняет, запускает и завершает durable-задачи конвертации."""

    def __init__(
        self,
        *,
        store: TaskStore,
        queue: TaskQueue,
        workspace_factory: Callable[[], ArtifactWorkspace],
        inspector: Callable[[Path], Any] = inspect_path,
        comparer: Callable[[Any, Any], Any] = compare_inspections,
    ) -> None:
        self._store = store
        self._queue = queue
        self._workspace_factory = workspace_factory
        self._inspector = inspector
        self._comparer = comparer

    def persist(
        self,
        task_id: str,
        source_path: Path,
        source: DocFormat,
        target: DocFormat,
        mode: ConversionMode,
        quality_policy: QualityPolicy | None = None,
        object_loss_policy: ObjectLossPolicy | None = None,
        require_unchanged_text: bool = False,
        text_preservation: str | None = None,
        max_text_edits: int | None = None,
        max_changed_formulas: int | None = None,
        max_changed_emphasis: int | None = None,
        max_changed_headings: int | None = None,
        txt_encoding: str = "auto",
    ) -> None:
        self._store.set(
            task_id,
            {
                "status": "queued",
                "queue_kind": "convert",
                "error": None,
                "report": None,
                "source_format": source.value,
                "target_format": target.value,
                "mode": mode.value,
                "source_name": source_path.name,
                **stored_policy_fields(
                    quality_policy,
                    object_loss_policy,
                    require_unchanged_text,
                    text_preservation,
                    max_text_edits,
                    max_changed_formulas,
                    max_changed_emphasis,
                    max_changed_headings,
                    txt_encoding,
                ),
            },
        )
        try:
            self._store.store_source(task_id, source_path, source_path.name)
        except Exception:
            self._store.delete(task_id)
            raise

    def resume(self, task_id: str) -> None:
        """Поставить ранее сохранённую задачу в очередь."""
        self._queue.submit_named(task_id, self.run_stored, task_id)

    def cancel(self, task_id: str) -> dict[str, Any]:
        """Запросить безопасную отмену и удалить незавершённый результат."""
        task = self._store.get(task_id)
        if task is None:
            raise KeyError(task_id)
        status = str(task.get("status"))
        if status not in {"queued", "running", "cancelling"}:
            raise ValueError("Эту задачу уже нельзя отменить")
        removed_from_queue = self._queue.cancel(task_id)
        next_status = self._store.request_cancel(task_id, removed_from_queue=removed_from_queue)
        if next_status is None:
            raise ValueError("Состояние задачи изменилось; готовый результат сохранён")
        return {"task_id": task_id, "status": next_status}

    def rerun(self, task_id: str) -> dict[str, Any]:
        """Повторить сохранённую задачу без потери результата при отказе записи."""
        return retry_saved_task(self._store, task_id, resume=self.resume)

    def run_stored(self, task_id: str) -> None:
        """Выполнить задачу только по сохранённому описанию и исходнику."""
        task = self._store.get(task_id)
        source_path = self._store.source_path(task_id)
        if task is None or source_path is None:
            if task is not None:
                self._store.set(task_id, {**task, "status": "error", "error": "Сохранённый исходник задачи недоступен"})
            return
        if task.get("status") in {"cancelled", "cancelling"}:
            self._mark_cancelled(task_id, task)
            return
        try:
            source = DocFormat(task["source_format"])
            target = DocFormat(task["target_format"])
            mode = ConversionMode(task["mode"])
        except (KeyError, ValueError) as error:
            self._store.set(task_id, {**task, "status": "error", "error": f"Некорректное описание задачи: {error}"})
            return
        workspace = self._workspace_factory()
        output_path = output_path_for(workspace, source_path, source, target)
        if self._is_cancelled(task_id):
            workspace.cleanup()
            self._mark_cancelled(task_id)
            return
        self._store.set(task_id, {**task, "status": "running", "error": None})
        self._run(task_id, source_path, output_path, source, target, mode, workspace)

    def _run(
        self,
        task_id: str,
        source_path: Path,
        output_path: Path,
        source: DocFormat,
        target: DocFormat,
        mode: ConversionMode,
        workspace: ArtifactWorkspace,
    ) -> None:
        source_inspection = None
        inspection_error = None
        task = self._store.get(task_id) or {}
        try:
            source_inspection, inspection_error = inspect_task_source(task, source_path, source, self._inspector)
            request = ConversionRequest(
                input_path=source_path,
                output_path=output_path,
                source=source,
                target=target,
                mode=mode,
                model_intermediates_only=True,
                **request_policy_fields(task),
            )
            executor = ConversionExecutor()

            def cancellation() -> bool:
                return self._is_cancelled(task_id)

            if "cancelled" in signature(executor.execute).parameters:
                report = executor.execute(request, cancelled=cancellation)
            else:
                report = executor.execute(request)
            report_payload = report.to_dict()
            if self._is_cancelled(task_id) or report.metrics.get("cancelled"):
                self._mark_cancelled(task_id)
                return
            if not report.success:
                error = next(
                    (issue["message"] for issue in report_payload["issues"] if issue["severity"] == "error"),
                    "Конвертация завершилась с ошибкой",
                )
                self._store.set(
                    task_id,
                    {
                        **task,
                        "status": "error",
                        "error": error,
                        "report": report_payload,
                        "source_inspection": inspection_payload(source_inspection, source_path.name),
                        "inspection_error": inspection_error,
                    },
                )
                return
            workspace.validate_artifact(output_path)
            filename, media_type = artifact_meta(output_path, source_path.stem, target)
            artifact_name = self._store.store_artifact(task_id, output_path, filename)
            target_inspection = None
            comparison = None
            if source_inspection is not None and output_path.is_file():
                try:
                    target_inspection = self._inspector(output_path)
                    comparison = self._comparer(source_inspection, target_inspection)
                except Exception as error:  # noqa: BLE001 - unsupported targets remain downloadable
                    inspection_error = f"Структурное сравнение результата недоступно: {error}"
            self._store.set(
                task_id,
                {
                    **task,
                    "status": "done",
                    "artifact": artifact_name,
                    "filename": filename,
                    "media_type": media_type,
                    "error": None,
                    "report": report_payload,
                    "source_inspection": inspection_payload(source_inspection, source_path.name),
                    "target_inspection": inspection_payload(target_inspection, filename),
                    "comparison": comparison.to_dict() if comparison is not None else None,
                    "inspection_error": inspection_error,
                },
            )
        except Exception as error:  # noqa: BLE001 - background task exposes a stable status
            if self._is_cancelled(task_id):
                self._mark_cancelled(task_id)
                return
            self._store.set(
                task_id,
                {
                    **task,
                    "status": "error",
                    "error": str(error),
                    "report": None,
                    "source_inspection": inspection_payload(source_inspection, source_path.name),
                    "inspection_error": inspection_error,
                },
            )
        finally:
            workspace.cleanup()

    def _is_cancelled(self, task_id: str) -> bool:
        task = self._store.get(task_id)
        return task is None or task.get("status") in {"cancelled", "cancelling"}

    def _mark_cancelled(self, task_id: str, task: dict[str, Any] | None = None) -> None:
        current = task or self._store.get(task_id)
        if current is not None:
            self._store.set(task_id, {**current, "status": "cancelled", "error": None, "report": None})
            self._store.clear_result(task_id)
