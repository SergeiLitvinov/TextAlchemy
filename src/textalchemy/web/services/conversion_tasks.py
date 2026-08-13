"""Жизненный цикл сохранённой задачи конвертации вне HTTP-слоя."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from typing import Any, Callable

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.inspection import compare_inspections, inspect_path
from textalchemy.core.types import DocFormat
from textalchemy.web.queue import TaskQueue
from textalchemy.web.services.conversion_catalog import MEDIA_TYPES, output_path_for
from textalchemy.web.tasks import TaskStore


def inspection_payload(inspection, display_name: str) -> dict[str, object] | None:
    """Подготовить результат инспекции для публичного API."""
    if inspection is None:
        return None
    payload = inspection.to_dict()
    payload["source_path"] = display_name
    return payload


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
    ) -> None:
        """Сохранить описание и исходник до постановки в очередь."""
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
        next_status = "cancelled" if removed_from_queue or status == "queued" else "cancelling"
        self._store.set(task_id, {**task, "status": next_status, "error": None, "report": None})
        self._store.clear_result(task_id)
        return {"task_id": task_id, "status": next_status}

    def rerun(self, task_id: str) -> dict[str, Any]:
        """Повторно поставить индивидуальную задачу по сохранённому исходнику."""
        task = self._store.get(task_id)
        if task is None or self._store.source_path(task_id) is None:
            raise KeyError(task_id)
        if task.get("queue_kind") != "convert":
            raise ValueError("Для этого типа задачи повтор пока недоступен")
        if task.get("status") in {"queued", "running", "cancelling"}:
            raise ValueError("Задача уже выполняется")
        self._store.clear_result(task_id)
        self._store.set(
            task_id,
            {
                **task,
                "status": "queued",
                "error": None,
                "report": None,
                "artifact": None,
                "filename": task.get("source_name") or task.get("filename"),
            },
        )
        self.resume(task_id)
        return {"task_id": task_id, "status": "queued"}

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
        try:
            try:
                source_inspection = self._inspector(source_path)
            except Exception as error:  # noqa: BLE001 - inspection must not block conversion
                inspection_error = f"Не удалось проверить исходный документ: {error}"
            request = ConversionRequest(input_path=source_path, output_path=output_path, source=source, target=target, mode=mode)
            executor = ConversionExecutor()

            def cancellation() -> bool:
                return self._is_cancelled(task_id)

            if "cancelled" in signature(executor.execute).parameters:
                report = executor.execute(request, cancelled=cancellation)
            else:
                report = executor.execute(request)
            report_payload = report.to_dict()
            if self._is_cancelled(task_id) or report.metrics.get("cancelled"):
                output_path.unlink(missing_ok=True)
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
                        "status": "error",
                        "error": error,
                        "report": report_payload,
                        "source_inspection": inspection_payload(source_inspection, source_path.name),
                        "inspection_error": inspection_error,
                    },
                )
                return
            workspace.validate_artifact(output_path)
            filename, media_type = self._artifact_meta(output_path, source_path.stem, target)
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

    @staticmethod
    def _artifact_meta(output_path: Path, source_stem: str, target: DocFormat) -> tuple[str, str]:
        if output_path.is_dir():
            return f"{source_stem}-html", "application/zip"
        return output_path.name, MEDIA_TYPES[target]
