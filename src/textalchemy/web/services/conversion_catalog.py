"""Каталог доступных Web-маршрутов конвертации и их представление."""

from __future__ import annotations

from pathlib import Path

from textalchemy.convert.executor import ConversionExecutor, infer_format
from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.core.conversion_graph import ConversionPlan
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.types import DocFormat

LEGACY_CONVERSIONS = {
    "pdf": (DocFormat.PDF, DocFormat.DOCX),
    "pptx": (DocFormat.PPTX, DocFormat.HTML),
    "latex": (DocFormat.DOCX, DocFormat.LATEX),
}
DEFAULT_TARGETS = {
    DocFormat.PDF: DocFormat.DOCX,
    DocFormat.PPTX: DocFormat.HTML,
    DocFormat.DOCX: DocFormat.PDF,
    DocFormat.MODEL: DocFormat.DOCX,
}
OUTPUT_SUFFIXES = {
    DocFormat.DOCX: ".docx",
    DocFormat.HTML: ".html",
    DocFormat.LATEX: ".tex",
    DocFormat.PDF: ".pdf",
    DocFormat.MODEL: ".json",
}
MEDIA_TYPES = {
    DocFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    DocFormat.HTML: "text/html; charset=utf-8",
    DocFormat.LATEX: "application/x-tex",
    DocFormat.PDF: "application/pdf",
    DocFormat.MODEL: "application/json",
}
FORMAT_LABELS = {
    DocFormat.PDF: "PDF",
    DocFormat.DOCX: "Word (DOCX)",
    DocFormat.PPTX: "PowerPoint (PPTX)",
    DocFormat.HTML: "HTML",
    DocFormat.LATEX: "LaTeX",
    DocFormat.MODEL: "TextAlchemy Model",
}
SOURCE_EXTENSIONS = {
    DocFormat.PDF: (".pdf",),
    DocFormat.DOCX: (".docx",),
    DocFormat.PPTX: (".pptx",),
    DocFormat.MODEL: (".json",),
}
MODE_ORDER = (ConversionMode.BALANCED, ConversionMode.FAITHFUL, ConversionMode.EDITABLE)


def resolve_conversion(
    source_path: Path,
    *,
    source_format: str,
    target_format: str,
    legacy_format: str,
) -> tuple[DocFormat, DocFormat]:
    """Определить исходный и целевой форматы пользовательского запроса."""
    if source_format == "auto" and legacy_format in LEGACY_CONVERSIONS:
        legacy_source, legacy_target = LEGACY_CONVERSIONS[legacy_format]
        return legacy_source, DocFormat(target_format) if target_format else legacy_target
    source = infer_format(source_path) if source_format == "auto" else DocFormat(source_format)
    target = DocFormat(target_format) if target_format else DEFAULT_TARGETS.get(source)
    if target is None:
        raise ValueError(f"Для формата {source.value} не задан формат результата")
    return source, target


def web_plan_supported(plan: ConversionPlan) -> bool:
    """Проверить, может ли Web выполнить план без файловых промежуточных форматов."""
    return all(step.target is DocFormat.MODEL for step in plan.steps[:-1])


def preservation_below(plan: ConversionPlan, threshold: float) -> dict[str, float]:
    """Return dimensions whose planned retention violates a user-selected budget."""
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("Минимальная сохранность должна быть от 0 до 1")
    if threshold == 0 or plan.preservation is None:
        return {}
    return {
        dimension.value: score
        for dimension, score in plan.preservation.scores.items()
        if score < threshold
    }


def available_conversions(executor: ConversionExecutor) -> dict[str, object]:
    """Построить пользовательский каталог реально достижимых направлений."""
    sources = []
    for source, extensions in SOURCE_EXTENSIONS.items():
        targets = []
        for target in OUTPUT_SUFFIXES:
            if target is source:
                continue
            plans = {
                mode.value: plan
                for mode in MODE_ORDER
                if (plan := executor.plan(source, target, mode=mode)) is not None and web_plan_supported(plan)
            }
            if not plans:
                continue
            targets.append(
                {
                    "format": target.value,
                    "label": FORMAT_LABELS[target],
                    "extension": OUTPUT_SUFFIXES[target],
                    "modes": list(plans),
                    "plans": {
                        mode: {
                            "lossless": plan.lossless,
                            "visual_score": plan.visual_score,
                            "editability_score": plan.editability_score,
                            "preservation": plan.preservation.to_dict() if plan.preservation else None,
                            "steps": [step.id for step in plan.steps],
                            "descriptions": [step.description or step.id for step in plan.steps],
                        }
                        for mode, plan in plans.items()
                    },
                }
            )
        if targets:
            sources.append(
                {
                    "format": source.value,
                    "label": FORMAT_LABELS[source],
                    "extensions": list(extensions),
                    "targets": targets,
                }
            )
    return {"sources": sources, "modes": [mode.value for mode in MODE_ORDER]}


def output_path_for(workspace: ArtifactWorkspace, source_path: Path, source: DocFormat, target: DocFormat) -> Path:
    """Выделить безопасный путь результата внутри workspace."""
    if source is DocFormat.PPTX and target is DocFormat.HTML:
        return workspace.artifact_path(f"{source_path.stem}-html")
    return workspace.artifact_path(f"{source_path.stem}{OUTPUT_SUFFIXES[target]}")
