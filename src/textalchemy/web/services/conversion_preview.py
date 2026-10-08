"""Предпросмотр сохранённого результата без HTTP и выдачи устаревшего кэша."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import Any, Callable

from textalchemy.quality.visual import difference_heatmap_png
from textalchemy.web.preview import DEFAULT_PREVIEW_DPI, MAX_PREVIEW_DPI, cached_page_count, cached_page_png
from textalchemy.web.tasks import TaskStore


class PreviewError(Exception):
    """Различать неверный запрос, отсутствующий результат и изменившуюся задачу."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class PreviewSnapshot:
    task_id: str
    task: dict[str, Any]
    cache: Path
    source: Path | None
    target: Path | None


@dataclass(frozen=True)
class PreviewImage:
    content: bytes
    similarity: float | None = None
    rmse: float | None = None


@dataclass(frozen=True)
class ConversionPreviewService:
    """Исходник, результат и различия относятся к одному сохранённому состоянию задачи."""

    store: TaskStore
    counter: Callable[..., int] = cached_page_count
    renderer: Callable[..., bytes | None] = cached_page_png
    comparer: Callable[..., Any] = difference_heatmap_png

    def meta(self, task_id: str) -> dict[str, Any]:
        snapshot = self._snapshot(task_id)
        result = {
            "source": self._side_meta(snapshot, snapshot.source, "source"),
            "target": self._side_meta(snapshot, snapshot.target, "target"),
        }
        self._verify(snapshot)
        return result

    def page(self, task_id: str, *, side: str = "source", page: int = 1, dpi: int = DEFAULT_PREVIEW_DPI) -> PreviewImage:
        if side not in {"source", "target"}:
            raise PreviewError("side must be 'source' or 'target'", 400)
        self._validate_page(page)
        snapshot = self._snapshot(task_id)
        file = snapshot.source if side == "source" else snapshot.target
        if file is None or not file.is_file():
            raise PreviewError("Source file is not available", 404)
        try:
            pages = self.counter(snapshot.cache, file, side)
        except Exception:  # noqa: BLE001 - недоступный движок не блокирует метаданные
            pages = 0
        if page > pages:
            self._verify(snapshot)
            raise PreviewError("Page is out of range", 404)
        data = self._render(snapshot, file, side, page, dpi)
        self._verify(snapshot)
        if data is None:
            raise PreviewError("Не удалось отрисовать страницу", 404)
        return PreviewImage(data)

    def diff(self, task_id: str, *, page: int = 1, dpi: int = DEFAULT_PREVIEW_DPI) -> PreviewImage:
        self._validate_page(page)
        snapshot = self._snapshot(task_id)
        if snapshot.source is None or snapshot.target is None:
            raise PreviewError("Source or result is not available", 404)
        source_png = self._render(snapshot, snapshot.source, "source", page, dpi)
        target_png = self._render(snapshot, snapshot.target, "target", page, dpi)
        self._verify(snapshot)
        if source_png is None or target_png is None:
            raise PreviewError("Не удалось отрисовать сравниваемые страницы", 404)
        try:
            data, comparison = self.comparer(source_png, target_png)
        except Exception as error:
            self._verify(snapshot)
            raise PreviewError("Не удалось сравнить страницы", 404) from error
        self._verify(snapshot)
        measurement = {
            "page": page,
            "dpi": max(1, min(dpi, MAX_PREVIEW_DPI)),
            "method": "normalised-grayscale-mae-v1",
            "normalization_pixels": [160, 160],
            "similarity": comparison.similarity,
            "rmse": comparison.root_mean_square_error,
            "source_png_sha256": sha256(source_png).hexdigest(),
            "target_png_sha256": sha256(target_png).hexdigest(),
            "source_name": snapshot.source.name,
            "target_name": snapshot.target.name,
            "source_format": snapshot.task.get("source_format"),
            "target_format": snapshot.task.get("target_format"),
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "versions": {name: version(name) for name in ("textalchemy", "opendoc-model", "opendoc-formats", "pillow")},
            "scope": "page_images_only",
            "editability_verified": None,
        }
        try:
            saved = self.store.store_preview_measurement(task_id, expected=snapshot.task, measurement=measurement)
        except OSError as error:
            self._verify(snapshot)
            raise PreviewError("Не удалось сохранить измерение; повторите сравнение", 503) from error
        if not saved:
            self._verify(snapshot)
            self._changed(task_id)
        return PreviewImage(data, comparison.similarity, comparison.root_mean_square_error)

    def _snapshot(self, task_id: str) -> PreviewSnapshot:
        task = self.store.get(task_id)
        if task is None:
            raise PreviewError("Task not found", 404)
        if task.get("status") != "done":
            raise PreviewError("Preview is not ready", 409)
        source = self.store.source_path(task_id)
        target = self.store.result_path(task_id, task.get("artifact", ""))
        cache = self.store.preview_revision_dir(task_id, expected=task)
        if cache is None:
            self._changed(task_id)
        return PreviewSnapshot(task_id, task, cache, source, target)

    def _verify(self, snapshot: PreviewSnapshot) -> None:
        if self.store.get(snapshot.task_id) != snapshot.task:
            self.store.discard_preview_revision(snapshot.task_id, snapshot.cache)
            self._changed(snapshot.task_id)

    def _changed(self, task_id: str) -> None:
        if self.store.get(task_id) is None:
            raise PreviewError("Task not found", 404)
        raise PreviewError("Результат изменился; обновите предпросмотр", 409)

    def _side_meta(self, snapshot: PreviewSnapshot, file: Path | None, side: str) -> dict[str, Any]:
        if file is None or not file.is_file():
            return {"available": False, "pages": 0, "error": None}
        try:
            pages = self.counter(snapshot.cache, file, side)
        except Exception as error:  # noqa: BLE001 - ошибки движков представлены на стороне документа
            return {"available": False, "pages": 0, "error": str(error)}
        return {"available": pages > 0, "pages": pages, "error": None}

    def _render(self, snapshot: PreviewSnapshot, file: Path, side: str, page: int, dpi: int) -> bytes | None:
        try:
            return self.renderer(snapshot.cache, file, side, page - 1, dpi=max(1, min(dpi, MAX_PREVIEW_DPI)))
        except Exception as error:
            self._verify(snapshot)
            raise PreviewError("Не удалось отрисовать страницу", 404) from error

    def _validate_page(self, page: int) -> None:
        if page < 1:
            raise PreviewError("page must be positive", 400)
