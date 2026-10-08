"""Каталог доступных Web-маршрутов конвертации и их представление."""

from __future__ import annotations

from pathlib import Path

from textalchemy.convert.executor import ConversionExecutor, infer_format
from textalchemy.convert.input_policy import WORKBOOK_EXTENSIONS, WORKBOOK_MESSAGE
from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.core.conversion_graph import ConversionPlan
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.types import DocFormat
from textalchemy.web.services.conversion_availability import unavailable_reason
from textalchemy.web.services.conversion_guidance import route_guidance

LEGACY_CONVERSIONS = {
    "pdf": (DocFormat.PDF, DocFormat.DOCX),
    "pptx": (DocFormat.PPTX, DocFormat.HTML),
    "latex": (DocFormat.DOCX, DocFormat.LATEX),
}
DEFAULT_TARGETS = {
    DocFormat.DJVU: DocFormat.TXT,
    DocFormat.PDF: DocFormat.DOCX,
    DocFormat.PPTX: DocFormat.HTML,
    DocFormat.DOCX: DocFormat.PDF,
    DocFormat.MODEL: DocFormat.DOCX,
    DocFormat.TXT: DocFormat.DOCX,
    DocFormat.EPUB: DocFormat.HTML,
    DocFormat.HTML: DocFormat.DOCX,
}
OUTPUT_SUFFIXES = {
    DocFormat.TXT: ".txt",
    DocFormat.PPTX: ".pptx",
    DocFormat.DOCX: ".docx",
    DocFormat.HTML: ".html",
    DocFormat.LATEX: ".tex",
    DocFormat.PDF: ".pdf",
    DocFormat.MODEL: ".json",
}
MEDIA_TYPES = {
    DocFormat.TXT: "text/plain; charset=utf-8",
    DocFormat.PPTX: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    DocFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    DocFormat.HTML: "text/html; charset=utf-8",
    DocFormat.LATEX: "application/x-tex",
    DocFormat.PDF: "application/pdf",
    DocFormat.MODEL: "application/json",
}
FORMAT_LABELS = {
    DocFormat.DJVU: "DjVu (текстовый слой)",
    DocFormat.EPUB: "Электронная книга (EPUB)",
    DocFormat.PDF: "PDF",
    DocFormat.DOCX: "Word (DOCX)",
    DocFormat.PPTX: "PowerPoint (PPTX)",
    DocFormat.HTML: "HTML",
    DocFormat.LATEX: "LaTeX",
    DocFormat.MODEL: "TextAlchemy Model",
    DocFormat.TXT: "Текст (TXT)",
}
SOURCE_EXTENSIONS = {
    DocFormat.DJVU: (".djvu",),
    DocFormat.HTML: (".html", ".htm"),
    DocFormat.EPUB: (".epub",),
    DocFormat.PDF: (".pdf",),
    DocFormat.DOCX: (".docx",),
    DocFormat.PPTX: (".pptx",),
    DocFormat.MODEL: (".json",),
    DocFormat.TXT: (".txt",),
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
    if source_path.suffix.lower() in WORKBOOK_EXTENSIONS:
        raise ValueError(WORKBOOK_MESSAGE)
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
    return {dimension.value: score for dimension, score in plan.preservation.scores.items() if score < threshold}


def available_conversions(executor: ConversionExecutor) -> dict[str, object]:
    """Построить пользовательский каталог реально достижимых направлений."""
    sources, unavailable_sources = [], []
    for source, extensions in SOURCE_EXTENSIONS.items():
        targets, unavailable_targets = [], []
        for target in OUTPUT_SUFFIXES:
            if target is source:
                continue
            entry = _target_entry(executor, source, target)
            (targets if entry["modes"] else unavailable_targets).append(entry)
        if targets:
            sources.append(
                {
                    "format": source.value,
                    "label": FORMAT_LABELS[source],
                    "extensions": list(extensions),
                    "default_target": next(
                        (
                            item["format"]
                            for item in targets
                            if item["format"] == DEFAULT_TARGETS.get(source, DocFormat.DOCX).value
                        ),
                        targets[0]["format"],
                    ),
                    "targets": targets,
                    "unavailable_targets": unavailable_targets,
                }
            )
        else:
            unavailable_sources.append(
                {
                    "format": source.value,
                    "label": FORMAT_LABELS[source],
                    "extensions": list(extensions),
                    "targets": [],
                    "unavailable_targets": unavailable_targets,
                }
            )
    return {
        "sources": sources,
        "unavailable_sources": unavailable_sources,
        "modes": [mode.value for mode in MODE_ORDER],
        "unsupported_inputs": [{"extensions": list(WORKBOOK_EXTENSIONS), "message": WORKBOOK_MESSAGE}],
    }


def _target_entry(executor: ConversionExecutor, source: DocFormat, target: DocFormat) -> dict[str, object]:
    plans, unavailable = {}, {}
    for mode in MODE_ORDER:
        plan = executor.plan(source, target, mode=mode, model_intermediates_only=True)
        if plan is None or not web_plan_supported(plan):
            unavailable[mode.value] = unavailable_reason(executor, source, target, mode, plan)
            continue
        plans[mode.value] = {
            "lossless": plan.lossless,
            "visual_score": plan.visual_score,
            "editability_score": plan.editability_score,
            "preservation": plan.preservation.to_dict() if plan.preservation else None,
            "steps": [step.id for step in plan.steps],
            "descriptions": [step.description or step.id for step in plan.steps],
        }
    return {
        "format": target.value,
        "label": FORMAT_LABELS[target],
        "extension": OUTPUT_SUFFIXES[target],
        "modes": list(plans),
        "plans": plans,
        "unavailable_modes": unavailable,
        "guidance": route_guidance(source, target),
    }


def output_path_for(workspace: ArtifactWorkspace, source_path: Path, source: DocFormat, target: DocFormat) -> Path:
    """Выделить безопасный путь результата внутри workspace."""
    if source is DocFormat.PPTX and target is DocFormat.HTML:
        return workspace.artifact_path(f"{source_path.stem}-html")
    return workspace.artifact_path(f"{source_path.stem}{OUTPUT_SUFFIXES[target]}")
