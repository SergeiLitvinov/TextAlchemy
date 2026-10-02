"""Извлечение текста или LaTeX из загруженного файла без HTTP-ответов."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.core.types import Document, Text
from textalchemy.extract import docx_to_latex
from textalchemy.pipeline.extract import extract_text
from textalchemy.pipeline.ingest import ingest_file
from textalchemy.web.services.upload_input import UploadSaver, UploadSource, save_input, staged_upload


@dataclass(frozen=True)
class ExtractedDownload:
    """Содержимое результата переживает освобождение временного каталога."""

    content: str
    filename: str


@dataclass
class ExtractionService:
    workspace_factory: Callable[[], ArtifactWorkspace] = ArtifactWorkspace
    saver: UploadSaver = save_input
    ingest: Callable[..., Document] = ingest_file
    read_text: Callable[..., Text] = extract_text
    latex_writer: Callable[..., Any] = docx_to_latex

    async def text(self, upload: UploadSource) -> dict[str, Any]:
        try:
            async with staged_upload(
                upload, fallback="extracted.txt", workspace_factory=self.workspace_factory, saver=self.saver
            ) as (_, source):
                document = self.ingest(path=source)
                text = self.read_text(doc=document)
                return {"success": True, "text": text.plain, "filename": upload.filename}
        except Exception as error:  # noqa: BLE001
            return {"success": False, "error": str(error)}

    async def latex(self, upload: UploadSource, *, doc_type: str = "manuscript") -> ExtractedDownload | dict[str, Any]:
        try:
            async with staged_upload(
                upload, fallback="document.docx", workspace_factory=self.workspace_factory, saver=self.saver
            ) as (workspace, source):
                output = workspace.artifact_path(f"{source.stem}.tex")
                self.latex_writer(source, output, doc_type)
                workspace.validate_artifact(output)
                return ExtractedDownload(output.read_text(encoding="utf-8"), output.name)
        except Exception as error:  # noqa: BLE001
            return {"success": False, "error": str(error)}
