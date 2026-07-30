"""Execution of capability-planned conversions."""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from textalchemy.convert.capabilities import create_capability_registry
from textalchemy.core.conversion_graph import (
    DEFAULT_FEATURES,
    CapabilityRegistry,
    ConverterCapabilities,
    DocumentFeature,
)
from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import ConversionMode, DocumentModel
from textalchemy.core.types import DocFormat

StepHandler = Callable[[Any, Path], tuple[Any, ConversionReport | None]]
RequirementChecker = Callable[[str], bool]

_MODULE_REQUIREMENTS = {
    "python-docx": "docx",
    "python-pptx": "pptx",
    "pymupdf": "fitz",
}


@dataclass(frozen=True)
class ConversionRequest:
    input_path: Path
    output_path: Path
    source: DocFormat
    target: DocFormat
    mode: ConversionMode = ConversionMode.BALANCED
    features: frozenset[DocumentFeature] = DEFAULT_FEATURES
    max_steps: int = 4


class ConversionExecutor:
    def __init__(
        self,
        *,
        registry: CapabilityRegistry | None = None,
        handlers: dict[str, StepHandler] | None = None,
        requirement_checker: RequirementChecker | None = None,
    ) -> None:
        self.registry = registry or create_capability_registry()
        self.handlers = handlers or _built_in_handlers()
        self.requirement_checker = requirement_checker or requirement_available

    def execute(self, request: ConversionRequest) -> ConversionReport:
        report = ConversionReport(request.output_path)
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
        plan = self.registry.plan(
            request.source,
            request.target,
            mode=request.mode,
            features=request.features,
            max_steps=request.max_steps,
            available=self._step_available,
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
            value: Any = _load_initial(request)
            if not plan.steps and request.target is not DocFormat.MODEL:
                request.output_path.parent.mkdir(parents=True, exist_ok=True)
                if request.input_path.resolve() != request.output_path.resolve():
                    shutil.copy2(request.input_path, request.output_path)
                return report
            for step in plan.steps:
                handler = self.handlers[step.id]
                value, step_report = handler(value, request.output_path)
                report.metrics["executed_steps"].append(step.id)
                if step_report is not None:
                    report.issues.extend(step_report.issues)
                    report.metrics["step_metrics"][step.id] = step_report.metrics
            if request.target is DocFormat.MODEL:
                if not isinstance(value, DocumentModel):
                    raise TypeError(f"route returned {type(value).__name__}, expected DocumentModel")
                from textalchemy.core.document_codec import save_document

                save_document(value, request.output_path)
            elif not request.output_path.exists():
                report.add(IssueSeverity.ERROR, "output", f"converter did not create {request.output_path}")
        except Exception as error:  # noqa: BLE001 - backends expose heterogeneous failures
            report.add(IssueSeverity.ERROR, "execution", str(error))
        return report

    def _step_available(self, step: ConverterCapabilities) -> bool:
        return step.id in self.handlers and all(self.requirement_checker(item) for item in step.requirements)


def requirement_available(requirement: str) -> bool:
    if requirement == "libreoffice":
        candidates = (
            shutil.which("soffice"),
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        )
        return any(candidate and Path(candidate).is_file() for candidate in candidates)
    module = _MODULE_REQUIREMENTS.get(requirement, requirement.replace("-", "_"))
    return importlib.util.find_spec(module) is not None


def infer_format(path: str | Path) -> DocFormat:
    suffix = Path(path).suffix.lower()
    aliases = {
        ".pdf": DocFormat.PDF,
        ".docx": DocFormat.DOCX,
        ".pptx": DocFormat.PPTX,
        ".html": DocFormat.HTML,
        ".htm": DocFormat.HTML,
        ".tex": DocFormat.LATEX,
        ".json": DocFormat.MODEL,
        ".txt": DocFormat.TXT,
        ".djvu": DocFormat.DJVU,
        ".epub": DocFormat.EPUB,
    }
    if suffix not in aliases:
        raise ValueError(f"cannot infer document format from suffix {suffix or '<none>'!r}")
    return aliases[suffix]


def _load_initial(request: ConversionRequest) -> Path | DocumentModel:
    if request.source is DocFormat.MODEL:
        from textalchemy.core.document_codec import load_document

        return load_document(request.input_path)
    return request.input_path


def _built_in_handlers() -> dict[str, StepHandler]:
    return {
        "docx.model": _docx_to_model,
        "model.docx": _model_to_docx,
        "model.html": _model_to_html,
        "model.pdf": _model_to_pdf,
        "pdf.docx.pdf2docx": _pdf2docx,
        "pdf.docx.libreoffice": _libreoffice_pdf_to_docx,
        "pdf.docx.pymupdf": _pymupdf_pdf_to_docx,
        "pptx.html": _pptx_to_html,
        "docx.latex": _docx_to_latex,
    }


def _docx_to_model(value: Any, _output: Path) -> tuple[DocumentModel, None]:
    from textalchemy.formats.docx import read_docx_model

    return read_docx_model(_require_path(value)), None


def _model_to_docx(value: Any, output: Path) -> tuple[Path, ConversionReport]:
    from textalchemy.convert.docx_writer import write_docx_model

    model = _require_model(value)
    return output, write_docx_model(model, output)


def _model_to_html(value: Any, output: Path) -> tuple[Path, ConversionReport]:
    from textalchemy.convert.html_writer import write_html_model

    model = _require_model(value)
    return output, write_html_model(model, output)


def _model_to_pdf(value: Any, output: Path) -> tuple[Path, ConversionReport]:
    from textalchemy.convert.pdf_writer import write_pdf_model

    model = _require_model(value)
    return output, write_pdf_model(model, output)


def _legacy_path_converter(value: Any, output: Path, tool: str) -> tuple[Path, ConversionReport]:
    from textalchemy.convert.pdf_to_docx import create_converter

    source = _require_path(value)
    legacy = create_converter(tool).convert(source, output)
    report = ConversionReport(output)
    report.metrics["engine"] = tool
    if not legacy.success:
        report.add(IssueSeverity.ERROR, "legacy-converter", legacy.error or f"{tool} failed")
    return output, report


def _pdf2docx(value: Any, output: Path) -> tuple[Path, ConversionReport]:
    return _legacy_path_converter(value, output, "pdf2docx")


def _libreoffice_pdf_to_docx(value: Any, output: Path) -> tuple[Path, ConversionReport]:
    return _legacy_path_converter(value, output, "libreoffice")


def _pymupdf_pdf_to_docx(value: Any, output: Path) -> tuple[Path, ConversionReport]:
    return _legacy_path_converter(value, output, "pymupdf")


def _pptx_to_html(value: Any, output: Path) -> tuple[Path, ConversionReport]:
    from textalchemy.convert.pptx_to_html import PptxToHtmlConverter

    legacy = PptxToHtmlConverter().convert(_require_path(value), output)
    report = ConversionReport(legacy.output_path)
    if not legacy.success:
        report.add(IssueSeverity.ERROR, "legacy-converter", legacy.error or "pptx2html failed")
    return legacy.output_path, report


def _docx_to_latex(value: Any, output: Path) -> tuple[Path, ConversionReport]:
    from textalchemy.convert.docx_to_latex import DocxToLatexConverter

    legacy = DocxToLatexConverter().convert(_require_path(value), output)
    report = ConversionReport(output)
    if not legacy.success:
        report.add(IssueSeverity.ERROR, "legacy-converter", legacy.error or "docx2latex failed")
    return output, report


def _require_path(value: Any) -> Path:
    if not isinstance(value, Path):
        raise TypeError(f"conversion step expected Path, got {type(value).__name__}")
    return value


def _require_model(value: Any) -> DocumentModel:
    if not isinstance(value, DocumentModel):
        raise TypeError(f"conversion step expected DocumentModel, got {type(value).__name__}")
    return value


__all__ = [
    "ConversionExecutor",
    "ConversionRequest",
    "infer_format",
    "requirement_available",
]
