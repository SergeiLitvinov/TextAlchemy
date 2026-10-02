"""Ограниченный временный файл из асинхронного потока без HTTP-типов."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

from textalchemy.core.artifacts import ArtifactWorkspace


class UploadSource(Protocol):
    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...


UploadSaver = Callable[..., Awaitable[Path]]


async def save_input(workspace: ArtifactWorkspace, upload: UploadSource, *, fallback: str) -> Path:
    return await workspace.write_upload(upload, upload.filename or fallback)


@asynccontextmanager
async def staged_upload(
    upload: UploadSource,
    *,
    fallback: str,
    workspace_factory: Callable[[], ArtifactWorkspace],
    saver: UploadSaver,
) -> AsyncIterator[tuple[ArtifactWorkspace, Path]]:
    """Освободить исходник и результаты при успехе, ошибке чтения или обработки."""
    workspace = workspace_factory()
    try:
        source = await saver(workspace, upload, fallback=fallback)
        yield workspace, source
    finally:
        workspace.cleanup()
