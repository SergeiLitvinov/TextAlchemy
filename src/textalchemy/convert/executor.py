"""Execution of capability-planned conversions."""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from textalchemy.convert.backends import ExporterBackend, ImporterBackend, PathConverterBackend
from textalchemy.convert.capabilities import create_capability_registry
from textalchemy.convert.protocols import ConversionBackend, ConversionValue
from textalchemy.core.conversion_graph import (
    DEFAULT_FEATURES,
    CapabilityRegistry,
    ConverterCapabilities,
    DocumentFeature,
)
from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import ConversionMode, DocumentModel
from textalchemy.core.types import DocFormat

StepHandler = Callable[[ConversionValue, Path], tuple[ConversionValue, ConversionReport | None]]
BackendEntry = ConversionBackend | StepHandler
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
        handlers: dict[str, BackendEntry] | None = None,
        requirement_checker: RequirementChecker | None = None,
    ) -> None:
        self.registry = registry or create_capability_registry()
        self.backends = _built_in_backends() if handlers is None else handlers
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
            value = _load_initial(request)
            if not plan.steps and request.target is not DocFormat.MODEL:
                request.output_path.parent.mkdir(parents=True, exist_ok=True)
                if request.input_path.resolve() != request.output_path.resolve():
                    shutil.copy2(request.input_path, request.output_path)
                return report
            for step in plan.steps:
                backend = self.backends[step.id]
                execute = backend.execute if isinstance(backend, ConversionBackend) else backend
                value, step_report = execute(value, request.output_path)
                report.metrics["executed_steps"].append(step.id)
                if step_report is not None:
                    report.issues.extend(step_report.issues)
                    report.metrics["step_metrics"][step.id] = step_report.metrics
                    if not step_report.success:
                        return report
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
        return step.id in self.backends and all(self.requirement_checker(item) for item in step.requirements)


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


def _built_in_backends() -> dict[str, ConversionBackend]:
    return {
        "docx.model": ImporterBackend("docx.model", _read_docx),
        "model.docx": ExporterBackend("model.docx", _write_docx),
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


def _read_docx(source: Path) -> DocumentModel:
    from textalchemy.formats.docx import read_docx_model

    return read_docx_model(source)


def _write_docx(model: DocumentModel, output: Path) -> ConversionReport:
    from textalchemy.convert.docx_writer import write_docx_model

    return write_docx_model(model, output)


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
