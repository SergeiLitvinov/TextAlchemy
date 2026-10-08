"""Общие настройки и одиночный запуск конвертации без HTTP."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from textalchemy.convert.executor import ConversionExecutor
from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.object_quality_policy import ObjectLossPolicy
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.types import DocFormat
from textalchemy.web.services.conversion_catalog import (
    OUTPUT_SUFFIXES,
    preservation_below,
    resolve_conversion,
    web_plan_supported,
)
from textalchemy.web.services.conversion_policy import stored_policy_fields
from textalchemy.web.services.upload_input import UploadSaver, UploadSource, save_input, staged_upload
from textalchemy.web.tasks import TaskStore


class ConversionRequestError(ValueError):
    """Ошибка настроек или порога сохранности с кодом для транспортного адаптера."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class SubmissionUnavailableError(Exception):
    """Отказ сохранения или очереди; ID существует только после полного сохранения."""

    def __init__(self, task_id: str | None = None) -> None:
        super().__init__("Очередь конвертации временно недоступна")
        self.task_id = task_id


@dataclass(frozen=True)
class ConversionSettings:
    """Единые ограничения одиночной и пакетной конвертации."""

    target_format: str = ""
    mode: str = "balanced"
    max_loss_issues: int | None = None
    max_lost_objects: int | None = None
    require_unchanged_text: bool = False
    text_preservation: str | None = None
    max_text_edits: int | None = None
    max_changed_formulas: int | None = None
    max_changed_emphasis: int | None = None
    max_changed_headings: int | None = None
    txt_encoding: str = "auto"

    def policies(self) -> tuple[QualityPolicy | None, ObjectLossPolicy | None]:
        quality = QualityPolicy(self.max_loss_issues) if self.max_loss_issues is not None else None
        objects = ObjectLossPolicy(self.max_lost_objects) if self.max_lost_objects is not None else None
        stored_policy_fields(
            quality,
            objects,
            self.require_unchanged_text,
            self.text_preservation,
            self.max_text_edits,
            self.max_changed_formulas,
            self.max_changed_emphasis,
            self.max_changed_headings,
            self.txt_encoding,
        )
        return quality, objects


def check_min_retention(value: float) -> None:
    """Единый диапазон порога до загрузки пакета и при проверке направления."""
    if not 0 <= value <= 1:
        raise ConversionRequestError("Минимальная сохранность должна быть от 0 до 1")


def check_conversion_route(
    executor: ConversionExecutor, source: DocFormat, target: DocFormat, mode: ConversionMode, min_retention: float
) -> None:
    """Общая проверка доступности направления и прогноза сохранности."""
    check_min_retention(min_retention)
    plan = executor.plan(source, target, mode=mode, model_intermediates_only=True)
    if plan is None or not web_plan_supported(plan):
        from textalchemy.web.services.conversion_availability import unavailable_reason

        reason = unavailable_reason(executor, source, target, mode, plan)
        raise ConversionRequestError(
            f"Маршрут {source.value} → {target.value} ({mode.value}) недоступен. {reason['message']}"
        )
    if target not in OUTPUT_SUFFIXES:
        raise ConversionRequestError(f"Формат результата {target.value} пока недоступен в Web UI")
    below = preservation_below(plan, min_retention)
    if below:
        details = ", ".join(f"{name}: {score:.0%}" for name, score in below.items())
        raise ConversionRequestError(f"Прогноз ниже выбранного порога {min_retention:.0%}: {details}", 422)


@dataclass(frozen=True)
class ConversionSubmissionService:
    """Сначала сохраняет исходник; отказ очереди оставляет задачу для восстановления."""

    store: TaskStore
    persist: Callable[..., None]
    resume: Callable[[str], None]
    workspace_factory: Callable[[], ArtifactWorkspace] = ArtifactWorkspace
    saver: UploadSaver = save_input
    resolver: Callable[..., tuple[DocFormat, DocFormat]] = resolve_conversion
    executor_factory: Callable[[], ConversionExecutor] = ConversionExecutor

    async def submit(
        self,
        upload: UploadSource,
        *,
        settings: ConversionSettings,
        source_format: str = "auto",
        legacy_format: str = "",
        min_retention: float = 0.0,
    ) -> dict[str, Any]:
        async with staged_upload(upload, fallback="document", workspace_factory=self.workspace_factory, saver=self.saver) as (
            _,
            source_path,
        ):
            try:
                source, target = self.resolver(
                    source_path,
                    source_format=source_format,
                    target_format=settings.target_format,
                    legacy_format=legacy_format,
                )
                mode = ConversionMode(settings.mode)
                quality, objects = settings.policies()
                check_conversion_route(self.executor_factory(), source, target, mode, min_retention)
            except ConversionRequestError:
                raise
            except ValueError as error:
                raise ConversionRequestError(str(error)) from error
            task_id = str(uuid.uuid4())
            self._persist(task_id, source_path, source, target, mode, settings, quality, objects)
        try:
            self.resume(task_id)
        except Exception as error:
            try:
                self.store.note_queue_failure(task_id, str(error))
            except OSError:
                pass  # Исходник и состояние queued уже сохранены; пояснение не обязательно для восстановления.
            raise SubmissionUnavailableError(task_id) from error
        return {
            "success": True,
            "task_id": task_id,
            "status": f"/api/convert/status/{task_id}",
            "result": f"/api/convert/result/{task_id}",
        }

    def _persist(
        self,
        task_id: str,
        path: Path,
        source: DocFormat,
        target: DocFormat,
        mode: ConversionMode,
        settings: ConversionSettings,
        quality: QualityPolicy | None,
        objects: ObjectLossPolicy | None,
    ) -> None:
        try:
            self.persist(
                task_id,
                path,
                source,
                target,
                mode,
                quality,
                objects,
                settings.require_unchanged_text,
                settings.text_preservation,
                settings.max_text_edits,
                settings.max_changed_formulas,
                settings.max_changed_emphasis,
                settings.max_changed_headings,
                settings.txt_encoding,
            )
        except Exception as error:
            self.store.delete(task_id)
            raise SubmissionUnavailableError() from error
