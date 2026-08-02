"""Safe lifecycle management for temporary conversion artifacts."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

DEFAULT_ARTIFACT_QUOTA = 100 * 1024 * 1024


class ArtifactLimitError(ValueError):
    """Raised when an artifact workspace exceeds its byte quota."""


class ArtifactWorkspace:
    """Own a temporary directory and remove it deterministically.

    Uploaded files are written through a sibling partial file and atomically
    moved into place only after their size has been validated.
    """

    def __init__(
        self,
        *,
        parent: str | Path | None = None,
        prefix: str = "textalchemy_",
        max_bytes: int = DEFAULT_ARTIFACT_QUOTA,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        parent_path = Path(parent).resolve() if parent is not None else None
        self.path = Path(tempfile.mkdtemp(prefix=prefix, dir=parent_path)).resolve()
        self.max_bytes = max_bytes
        self.used_bytes = 0
        self._closed = False

    def artifact_path(self, name: str, *, fallback: str = "artifact") -> Path:
        """Return a path contained directly in this workspace."""

        self._ensure_open()
        safe_name = _safe_filename(name, fallback=fallback)
        return self.path / safe_name

    def write_bytes(self, name: str, data: bytes, *, fallback: str = "artifact") -> Path:
        """Atomically write a byte artifact after enforcing the workspace quota."""

        target = self.artifact_path(name, fallback=fallback)
        previous_size = target.stat().st_size if target.exists() else 0
        self._check_quota(len(data) - previous_size)
        partial = self.path / f".{target.name}.{uuid.uuid4().hex}.partial"
        try:
            partial.write_bytes(data)
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        self.used_bytes += len(data) - previous_size
        return target

    async def write_upload(self, upload: Any, name: str | None = None, *, chunk_size: int = 1024 * 1024) -> Path:
        """Stream an async upload into the workspace without partial artifacts."""

        target = self.artifact_path(name or getattr(upload, "filename", "") or "upload", fallback="upload")
        partial = self.path / f".{target.name}.{uuid.uuid4().hex}.partial"
        written = 0
        try:
            with partial.open("wb") as stream:
                while chunk := await upload.read(chunk_size):
                    written += len(chunk)
                    self._check_quota(written)
                    stream.write(chunk)
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        self.used_bytes += written
        return target

    def validate_artifact(self, artifact: str | Path) -> Path:
        """Validate that a produced artifact stays inside the workspace and quota."""

        self._ensure_open()
        resolved = Path(artifact).resolve()
        if resolved != self.path and self.path not in resolved.parents:
            raise ValueError("artifact is outside the workspace")
        size = (
            sum(path.stat().st_size for path in resolved.rglob("*") if path.is_file())
            if resolved.is_dir()
            else resolved.stat().st_size
        )
        self._check_quota(size)
        return resolved

    def cleanup(self) -> None:
        if self._closed:
            return
        shutil.rmtree(self.path, ignore_errors=True)
        self._closed = True

    def __enter__(self) -> "ArtifactWorkspace":
        self._ensure_open()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.cleanup()

    def _check_quota(self, additional_bytes: int) -> None:
        if additional_bytes > self.max_bytes - self.used_bytes:
            raise ArtifactLimitError(f"artifact quota exceeded ({self.max_bytes} bytes)")

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("artifact workspace is closed")


def _safe_filename(name: str, *, fallback: str) -> str:
    normalized = str(name).replace("\\", "/").replace("\x00", "")
    candidate = normalized.rsplit("/", 1)[-1].strip()
    if candidate in {"", ".", ".."}:
        candidate = fallback
    if len(candidate) > 160:
        suffix = Path(candidate).suffix[:20]
        candidate = f"{Path(candidate).stem[: 160 - len(suffix)]}{suffix}"
    return candidate


__all__ = ["ArtifactLimitError", "ArtifactWorkspace", "DEFAULT_ARTIFACT_QUOTA"]
