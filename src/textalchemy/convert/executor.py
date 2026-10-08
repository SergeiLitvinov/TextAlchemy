"""Execution of capability-planned conversions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from textalchemy.convert.backends import ExporterBackend, PathConverterBackend
from textalchemy.convert.capabilities import create_capability_registry
from textalchemy.convert.heading_budget import HeadingBudget
from textalchemy.convert.protocols import ConversionBackend, ConversionValue
from textalchemy.convert.publication import _cancelled_report
from textalchemy.convert.runtime_policy import infer_format, requirement_available
from textalchemy.convert.stages import StageContext
from textalchemy.core.conversion_graph import (
    DEFAULT_FEATURES,
    CapabilityRegistry,
    ConversionPlan,
    ConverterCapabilities,
    DocumentFeature,
)
from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import ConversionMode, DocumentModel
from textalchemy.core.emphasis_quality import EmphasisLossPolicy
from textalchemy.core.formula_quality_policy import FormulaLossPolicy
from textalchemy.core.object_quality_policy import ObjectLossPolicy
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.text_quality_policy import TextPreservationPolicy
from textalchemy.core.types import DocFormat

StepHandler = Callable[[ConversionValue, Path], tuple[ConversionValue, ConversionReport | None]]
BackendEntry = ConversionBackend | StepHandler
RequirementChecker = Callable[[str], bool]
CancellationCheck = Callable[[], bool]




@dataclass(frozen=True)
class ConversionRequest:
    input_path: Path
    output_path: Path
    source: DocFormat
    target: DocFormat
    mode: ConversionMode = ConversionMode.BALANCED
    features: frozenset[DocumentFeature] = DEFAULT_FEATURES
    max_steps: int = 4
    quality_policy: QualityPolicy | None = None
    object_loss_policy: ObjectLossPolicy | None = None
    text_preservation_policy: TextPreservationPolicy | None = None
    formula_loss_policy: FormulaLossPolicy | None = None
    emphasis_loss_policy: EmphasisLossPolicy | None = None
    heading_loss_policy: HeadingBudget | None = None
    txt_encoding: str = "auto"
    model_intermediates_only: bool = False

    def __post_init__(self) -> None:
        from opendoc_formats.text_profile import TextProfile

        TextProfile(self.txt_encoding)


class ConversionExecutor:
    def __init__(
        self,
        *,
        registry: CapabilityRegistry | None = None,
        handlers: dict[str, BackendEntry] | None = None,
        requirement_checker: RequirementChecker | None = None,
    ) -> None:
        self.registry = registry or create_capability_registry()
        self.backends = _built_in_backends() if handlers is None else handlers
        self.requirement_checker = requirement_checker or requirement_available

    def plan(
        self,
        source: DocFormat,
        target: DocFormat,
        *,
        mode: ConversionMode = ConversionMode.BALANCED,
        features: frozenset[DocumentFeature] = DEFAULT_FEATURES,
        max_steps: int = 4,
        model_intermediates_only: bool = False,
    ) -> ConversionPlan | None:
        """Построить маршрут, доступный в текущем runtime-окружении."""

        return self.registry.plan(
            source,
            target,
            mode=mode,
            features=features,
            max_steps=max_steps,
            available=lambda step: self._step_available(step) and (
                (not model_intermediates_only and target is not DocFormat.MODEL) or step.target in {DocFormat.MODEL, target}
            ),
        )

    def execute(self, request: ConversionRequest, *, cancelled: CancellationCheck | None = None) -> ConversionReport:
        from textalchemy.convert.publication import execute_with_quality

        return execute_with_quality(self, request, cancelled=cancelled)

    def _execute(self, request: ConversionRequest, *, cancelled: CancellationCheck | None = None) -> ConversionReport:
        report = ConversionReport(request.output_path)
        is_cancelled = cancelled or (lambda: False)
        if not request.input_path.is_file():
            report.add(IssueSeverity.ERROR, "input", f"input file not found: {request.input_path}")
            return report

        theoretical = self.registry.plan(
            request.source,
            request.target,
            mode=request.mode,
            features=request.features,
            max_steps=request.max_steps,
        )
        plan = self.plan(
            request.source,
            request.target,
            mode=request.mode,
            features=request.features,
            max_steps=request.max_steps,
            model_intermediates_only=request.model_intermediates_only,
        )
        if plan is None:
            if theoretical is None:
                message = f"conversion route not found: {request.source.value} -> {request.target.value}"
            else:
                missing = [
                    requirement
                    for requirement in theoretical.executable_requirements
                    if not self.requirement_checker(requirement)
                ]
                message = "conversion route is unavailable"
                if missing:
                    message += ": missing " + ", ".join(missing)
            report.add(IssueSeverity.ERROR, "route", message)
            return report

        report.metrics["plan"] = plan.to_dict()
        report.metrics["executed_steps"] = []
        report.metrics["step_metrics"] = {}
        try:
            if is_cancelled():
                return _cancelled_report(report)
            if request.source is DocFormat.MODEL:
                from textalchemy.convert.library_import import import_document

                value, initial_report = import_document(request.input_path, request.output_path, "json", cancelled=is_cancelled)
                report.issues.extend(initial_report.issues)
                report.metrics["source_import"] = initial_report.metrics
                if not initial_report.success:
                    return report
                if request.quality_policy is not None and not request.quality_policy.evaluate(report):
                    return report
            else:
                value = _load_initial(request)
            if not plan.steps and request.target is not DocFormat.MODEL:
                request.output_path.parent.mkdir(parents=True, exist_ok=True)
                if request.input_path.resolve() != request.output_path.resolve():
                    from textalchemy.core.io import atomic_copy

                    atomic_copy(request.input_path, request.output_path)
                if request.quality_policy is not None:
                    request.quality_policy.evaluate(report)
                return report
            for step in plan.steps:
                if is_cancelled():
                    return _cancelled_report(report)
                backend = self.backends[step.id]
                if backend is _import_txt:
                    from textalchemy.convert.library_import import import_document

                    value, step_report = import_document(
                        value, request.output_path, "txt", txt_encoding=request.txt_encoding, cancelled=is_cancelled)
                elif isinstance(backend, ConversionBackend) and hasattr(backend, "execute_stage"):
                    stage_result = backend.execute_stage(value, StageContext(request.output_path, is_cancelled))
                    value, step_report = stage_result.value, stage_result.report
                else:
                    execute = backend.execute if isinstance(backend, ConversionBackend) else backend
                    value, step_report = execute(value, request.output_path)
                report.metrics["executed_steps"].append(step.id)
                if step_report is not None:
                    report.issues.extend(step_report.issues)
                    report.metrics["step_metrics"][step.id] = step_report.metrics
                    if request.quality_policy is not None and not request.quality_policy.evaluate(report):
                        return report
                    if not step_report.success:
                        return report
                if is_cancelled():
                    if request.output_path.is_file():
                        request.output_path.unlink(missing_ok=True)
                    return _cancelled_report(report)
            if request.target is DocFormat.MODEL:
                if not isinstance(value, DocumentModel):
                    raise TypeError(f"route returned {type(value).__name__}, expected DocumentModel")
                from textalchemy.core.document_codec import save_document

                save_document(value, request.output_path)
            elif not request.output_path.exists():
                report.add(IssueSeverity.ERROR, "output", f"converter did not create {request.output_path}")
        except Exception as error:  # noqa: BLE001 - backends expose heterogeneous failures
            report.add(IssueSeverity.ERROR, "execution", str(error))
        if request.quality_policy is not None:
            request.quality_policy.evaluate(report)
        return report

    def _step_available(self, step: ConverterCapabilities) -> bool:
        return step.id in self.backends and all(self.requirement_checker(item) for item in step.requirements)


def _load_initial(request: ConversionRequest) -> Path | DocumentModel:
    if request.source is DocFormat.MODEL:
        from textalchemy.core.document_codec import load_document

        return load_document(request.input_path)
    return request.input_path


def _built_in_backends() -> dict[str, ConversionBackend]:
    return {
        "pdf.model": _import_pdf,
        "djvu.model": _import_djvu,
        "txt.model": _import_txt,
        "epub.model": _import_epub,
        "html.model": _import_html,
        "docx.model": _import_docx,
        "pptx.model": _import_pptx,
        "model.docx": ExporterBackend("model.docx", _write_docx),
        "model.pptx": ExporterBackend("model.pptx", _write_pptx),
        "model.txt": ExporterBackend("model.txt", _write_txt),
        "model.html": ExporterBackend("model.html", _write_html),
        "model.pdf": ExporterBackend("model.pdf", _write_pdf),
        "pdf.docx.pdf2docx": PathConverterBackend(
            "pdf.docx.pdf2docx",
            lambda source, output: _convert_pdf(source, output, "pdf2docx"),
        ),
        "pdf.docx.libreoffice": PathConverterBackend(
            "pdf.docx.libreoffice",
            lambda source, output: _convert_pdf(source, output, "libreoffice"),
        ),
        "pdf.docx.pymupdf": PathConverterBackend(
            "pdf.docx.pymupdf",
            lambda source, output: _convert_pdf(source, output, "pymupdf"),
        ),
        "pptx.html": PathConverterBackend("pptx.html", _convert_pptx_html),
        "docx.latex": PathConverterBackend("docx.latex", _convert_docx_latex),
    }


def _import_pdf(source: ConversionValue, output: Path) -> tuple[DocumentModel | None, ConversionReport]:
    from textalchemy.convert.library_import import import_document

    return import_document(source, output, "pdf")


def _import_txt(source: ConversionValue, output: Path) -> tuple[DocumentModel | None, ConversionReport]:
    from textalchemy.convert.library_import import import_document

    return import_document(source, output, "txt")


def _import_docx(source: ConversionValue, output: Path) -> tuple[DocumentModel | None, ConversionReport]:
    from textalchemy.convert.library_import import import_document

    return import_document(source, output, "docx")


def _import_pptx(source: ConversionValue, output: Path) -> tuple[DocumentModel | None, ConversionReport]:
    from textalchemy.convert.library_import import import_document

    return import_document(source, output, "pptx")


def _import_epub(source: ConversionValue, output: Path) -> tuple[DocumentModel | None, ConversionReport]:
    from textalchemy.convert.library_import import import_document

    return import_document(source, output, "epub")



def _import_djvu(source: ConversionValue, output: Path) -> tuple[DocumentModel, ConversionReport]:
    from opendoc_formats import read_document
    from opendoc_model import inspect_document_model

    if not isinstance(source, Path):
        raise TypeError("DjVu importer requires a path")
    result = read_document(source, format_id="djvu")
    if not result.success or result.document is None:
        raise ValueError("; ".join(issue.message for issue in result.issues) or "DjVu import failed")
    inspection = inspect_document_model(result.document)
    if inspection.metadata["text_flow"]["characters"] == 0:
        raise ValueError("В DjVu нет доступного текстового слоя. Для скана требуется распознавание текста.")
    report = ConversionReport(output)
    for issue in result.issues:
        report.add(issue.severity, issue.code, issue.message, issue.location)
    report.add(
        IssueSeverity.WARNING, "djvu-text-only",
        "Перенесён только текстовый слой DjVu. Страницы, координаты, изображения и оформление "
        "не восстанавливаются; распознавание сканов не выполняется.",
    )
    report.metrics.update(import_scope="text_layer_only", page_geometry_verified=None, ocr_performed=False)
    return result.document, report


def _import_html(source: ConversionValue, output: Path) -> tuple[DocumentModel, ConversionReport]:
    from textalchemy.formats.html import read_html_model

    if not isinstance(source, Path):
        raise TypeError("HTML importer requires a path")
    model = read_html_model(source)
    report = ConversionReport(output)
    report.metrics["html_locations"] = model.metadata["html"]["locations"]
    for item in model.metadata["html"]["warnings"]:
        report.add(IssueSeverity.LOSS, item["feature"], item["message"], item["location"])
    return model, report





def _write_docx(model: DocumentModel, output: Path) -> ConversionReport:
    from textalchemy.convert.docx_writer import write_docx_model

    return write_docx_model(model, output)


def _write_pptx(model: DocumentModel, output: Path) -> ConversionReport:
    from textalchemy.convert.pptx_writer import write_pptx_model

    return write_pptx_model(model, output)


def _write_txt(model: DocumentModel, output: Path) -> ConversionReport:
    from textalchemy.convert.txt_writer import write_txt_model

    return write_txt_model(model, output)


def _write_html(model: DocumentModel, output: Path) -> ConversionReport:
    from textalchemy.convert.html_writer import write_html_model

    return write_html_model(model, output)


def _write_pdf(model: DocumentModel, output: Path) -> ConversionReport:
    from textalchemy.convert.pdf_writer import write_pdf_model

    return write_pdf_model(model, output)


def _convert_pdf(source: Path, output: Path, tool: str) -> ConversionReport:
    from textalchemy.convert.pdf_to_docx import create_converter

    report = create_converter(tool).convert(source, output)
    report.metrics["engine"] = tool
    if report.success:
        return report
    primary_error = report.error or "conversion failed"
    for fallback_tool in ("pymupdf", "pdf2docx"):
        if fallback_tool == tool:
            continue
        output.unlink(missing_ok=True)
        fallback = create_converter(fallback_tool).convert(source, output)
        fallback.metrics["engine"] = fallback_tool
        fallback.metrics["requested_engine"] = tool
        if fallback.success:
            fallback.add(
                IssueSeverity.WARNING,
                "engine-fallback",
                f"{tool} failed ({primary_error}); used {fallback_tool}",
            )
            return fallback
    return report


def _convert_pptx_html(source: Path, output: Path) -> ConversionReport:
    from textalchemy.convert.pptx_to_html import PptxToHtmlConverter

    return PptxToHtmlConverter().convert(source, output)


def _convert_docx_latex(source: Path, output: Path) -> ConversionReport:
    from textalchemy.convert.docx_to_latex import DocxToLatexConverter

    return DocxToLatexConverter().convert(source, output)


__all__ = [
    "ConversionExecutor",
    "ConversionRequest",
    "infer_format",
    "requirement_available",
]
