"""Быстрый просмотр шаблона через HTML без офисного рендера и сохранения задачи."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.core.exceptions import GenerateError
from textalchemy.generate.model_template import generate_html_template
from textalchemy.web.services.generator_catalog import resolve_web_template, template_schema_for
from textalchemy.web.services.generator_execution import GeneratorService

MAX_PREVIEW_BYTES = 8 * 1024 * 1024


def _html_result(path: Path, format: str) -> dict[str, Any]:
    """Вернуть самодостаточный HTML; файл остаётся во временном workspace."""
    if format != "html" or path.stat().st_size > MAX_PREVIEW_BYTES:
        raise ValueError("Быстрый просмотр слишком большой. Используйте страницы результата или скачайте документ.")
    return {"success": True, "html": path.read_text(encoding="utf-8"), "kind": "structural"}


@dataclass
class LivePreviewService:
    """Использовать существующие генератор и форматные адаптеры для чернового HTML."""

    resolve_template: Callable[[str], Path] = resolve_web_template
    schema_provider: Callable[..., Any] = template_schema_for
    workspace_factory: Callable[[], ArtifactWorkspace] = ArtifactWorkspace

    def preview(self, *, template: str, params: str = "{}", source: bool = False) -> dict[str, Any]:
        """Не создавать скачиваемый результат и не запускать LibreOffice."""
        if not source:
            generator = GeneratorService(
                store_generated_preview=_html_result,
                resolve_template=self.resolve_template,
                schema_provider=self.schema_provider,
                workspace_factory=self.workspace_factory,
                generate_html_template=generate_html_template,
            )
            return generator.generate(template=template, output="preview.html", format="html", params=params, preview=True)
        from textalchemy.convert.html_writer import write_html_model
        from textalchemy.formats.docx import read_docx_model

        try:
            path = self.resolve_template(template)
            if path.suffix.lower() != ".docx":
                raise GenerateError("Быстрый просмотр исходника доступен для DOCX-шаблонов.")
            workspace = self.workspace_factory()
            try:
                output = workspace.artifact_path("source.html")
                write_html_model(read_docx_model(path), output)
                return {**_html_result(output, "html"), "draft": False, "missing_fields": []}
            finally:
                workspace.cleanup()
        except (GenerateError, OSError, ValueError) as error:
            return {"success": False, "error": str(error)}
