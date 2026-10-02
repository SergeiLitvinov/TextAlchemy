"""Подготовка и сохранение пакета до передачи заданий в очередь."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from textalchemy.convert.executor import ConversionExecutor
from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.object_quality_policy import ObjectLossPolicy
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.types import DocFormat
from textalchemy.web.services.batch_options import parse_batch_options
from textalchemy.web.services.batch_retry import submit_saved_tasks
from textalchemy.web.services.conversion_catalog import resolve_conversion
from textalchemy.web.services.conversion_submission import ConversionRequestError as BatchRequestError
from textalchemy.web.services.conversion_submission import ConversionSettings as BatchSettings
from textalchemy.web.services.conversion_submission import check_conversion_route, check_min_retention
from textalchemy.web.services.upload_input import UploadSaver, UploadSource, save_input
from textalchemy.web.tasks import TaskStore

BATCH_LIMIT = 20


@dataclass(frozen=True)
class PreparedBatchFile:
    """Проверенный исходник во временном каталоге перед долговременным сохранением."""

    path: Path
    source: DocFormat
    target: DocFormat
    mode: ConversionMode


@dataclass(frozen=True)
class BatchSubmissionService:
    """Все файлы проверяются до сохранения; очередь вызывается после сохранения пакета."""

    store: TaskStore
    persist: Callable[..., None]
    resume: Callable[[str], None]
    workspace_factory: Callable[[], ArtifactWorkspace] = ArtifactWorkspace
    saver: UploadSaver = save_input
    resolver: Callable[..., tuple[DocFormat, DocFormat]] = resolve_conversion
    executor_factory: Callable[[], ConversionExecutor] = ConversionExecutor

    async def submit(
        self, files: list[UploadSource], *, settings: BatchSettings, file_options: str = "", min_retention: float = 0.0
    ) -> dict[str, Any]:
        if not files or len(files) > BATCH_LIMIT:
            raise BatchRequestError(
                "Не передано ни одного файла" if not files else f"Слишком много файлов: максимум {BATCH_LIMIT}"
            )
        try:
            mode = ConversionMode(settings.mode)
            options = parse_batch_options(file_options, len(files), target=settings.target_format, mode=mode)
            quality, objects = settings.policies()
            check_min_retention(min_retention)
        except ValueError as error:
            raise BatchRequestError(str(error)) from error
        workspaces: list[ArtifactWorkspace] = []
        prepared: list[PreparedBatchFile] = []
        try:
            executor = self.executor_factory()
            for upload, option in zip(files, options):
                workspace = self.workspace_factory()
                workspaces.append(workspace)
                path = await self.saver(workspace, upload, fallback="document")
                try:
                    source, target = self.resolver(path, source_format="auto", target_format=option.target, legacy_format="")
                except ValueError as error:
                    raise BatchRequestError(str(error)) from error
                check_conversion_route(executor, source, target, option.mode, min_retention)
                prepared.append(PreparedBatchFile(path, source, target, option.mode))
            result = self._persist(prepared, settings, quality, objects)
        finally:
            for workspace in workspaces:
                workspace.cleanup()
        submit_saved_tasks(self.store, [item["task_id"] for item in result["tasks"]], resume=self.resume)
        return result

    def _persist(
        self,
        files: list[PreparedBatchFile],
        settings: BatchSettings,
        quality: QualityPolicy | None,
        objects: ObjectLossPolicy | None,
    ) -> dict[str, Any]:
        task_ids: list[str] = []
        tasks: list[dict[str, Any]] = []
        job_id = str(uuid.uuid4())
        try:
            for item in files:
                task_id = str(uuid.uuid4())
                task_ids.append(task_id)
                self.persist(
                    task_id,
                    item.path,
                    item.source,
                    item.target,
                    item.mode,
                    quality,
                    objects,
                    settings.require_unchanged_text,
                    settings.text_preservation,
                    settings.max_text_edits,
                    settings.max_changed_formulas,
                    settings.max_changed_emphasis,
                )
                tasks.append(
                    {
                        "name": item.path.name,
                        "task_id": task_id,
                        "source_format": item.source.value,
                        "target_format": item.target.value,
                        "mode": item.mode.value,
                        "status": f"/api/convert/status/{task_id}",
                        "result": f"/api/convert/result/{task_id}",
                    }
                )
            self.store.set_job(job_id, {"job_id": job_id, **asdict(settings), "files": tasks})
        except Exception:
            self.store.delete_job(job_id)
            for task_id in task_ids:
                self.store.delete(task_id)
            raise
        return {"success": True, "job_id": job_id, "tasks": tasks}
