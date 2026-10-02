"""Структурная инспекция загруженного файла с безопасным освобождением исходника."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.core.inspection import inspect_path
from textalchemy.web.services.conversion_results import inspection_payload
from textalchemy.web.services.upload_input import UploadSaver, UploadSource, save_input, staged_upload


@dataclass(frozen=True)
class ConversionInspectionService:
    """Рабочий поток завершает чтение до очистки, даже если HTTP-запрос отменён."""

    workspace_factory: Callable[[], ArtifactWorkspace] = ArtifactWorkspace
    saver: UploadSaver = save_input
    inspector: Callable[[Path], Any] = inspect_path

    async def inspect(self, upload: UploadSource) -> dict[str, Any]:
        async with staged_upload(upload, fallback="document", workspace_factory=self.workspace_factory, saver=self.saver) as (
            _,
            source,
        ):
            worker = asyncio.create_task(asyncio.to_thread(self._inspect, source))
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                await asyncio.gather(worker, return_exceptions=True)
                raise

    def _inspect(self, source: Path) -> dict[str, Any]:
        return {"success": True, "inspection": inspection_payload(self.inspector(source), source.name)}
