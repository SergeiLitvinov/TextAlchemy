"""Web-facing helpers for bounded artifact workspaces."""

from pathlib import Path

from fastapi import HTTPException, UploadFile

from textalchemy.core.artifacts import ArtifactLimitError, ArtifactWorkspace

WEB_UPLOAD_LIMIT_BYTES = 100 * 1024 * 1024


def create_web_workspace() -> ArtifactWorkspace:
    return ArtifactWorkspace(prefix="textalchemy_web_", max_bytes=WEB_UPLOAD_LIMIT_BYTES)


async def save_upload(workspace: ArtifactWorkspace, upload: UploadFile, *, fallback: str) -> Path:
    try:
        return await workspace.write_upload(upload, upload.filename or fallback)
    except ArtifactLimitError as error:
        raise HTTPException(status_code=413, detail=f"Файл превышает лимит {WEB_UPLOAD_LIMIT_BYTES} байт") from error


__all__ = ["WEB_UPLOAD_LIMIT_BYTES", "create_web_workspace", "save_upload"]
