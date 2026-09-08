from textalchemy.convert.backends import ExporterBackend, ImporterBackend, PathConverterBackend
from textalchemy.convert.base import BaseConverter, ConversionResult
from textalchemy.convert.capabilities import built_in_capabilities, create_capability_registry
from textalchemy.convert.docx_to_latex import DocxToLatexConverter
from textalchemy.convert.docx_writer import write_docx_model
from textalchemy.convert.executor import ConversionExecutor, ConversionRequest, infer_format
from textalchemy.convert.html_writer import write_html_model
from textalchemy.convert.pdf_to_docx import (
    FanOutConverter,
    LibreOfficeConverter,
    Pdf2DocxConverter,
    PyMuPdfConverter,
    create_converter,
)
from textalchemy.convert.pdf_writer import write_pdf_model
from textalchemy.convert.pptx_writer import write_pptx_model
from textalchemy.convert.protocols import (
    ConversionBackend,
    ConversionValue,
    DocumentExporter,
    DocumentImporter,
    PathConverter,
)
from textalchemy.convert.txt_writer import write_txt_model

__all__ = [
    "BaseConverter",
    "ConversionBackend",
    "ConversionExecutor",
    "ConversionRequest",
    "ConversionResult",
    "ConversionValue",
    "DocxToLatexConverter",
    "DocumentExporter",
    "DocumentImporter",
    "ExporterBackend",
    "FanOutConverter",
    "ImporterBackend",
    "LibreOfficeConverter",
    "PathConverter",
    "PathConverterBackend",
    "Pdf2DocxConverter",
    "PptxToHtmlConverter",
    "PyMuPdfConverter",
    "built_in_capabilities",
    "create_capability_registry",
    "create_converter",
    "infer_format",
    "pptx_to_html",
    "write_docx_model",
    "write_html_model",
    "write_pdf_model",
    "write_pptx_model",
    "write_txt_model",
]


def __getattr__(name: str) -> object:
    """Ленивая загрузка тяжёлых конвертеров (python-pptx) по требованию."""
    if name in {"PptxToHtmlConverter", "pptx_to_html"}:
        from textalchemy.convert.pptx_to_html import PptxToHtmlConverter
        from textalchemy.convert.pptx_to_html import convert as _pptx_to_html

        if name == "PptxToHtmlConverter":
            return PptxToHtmlConverter
        return _pptx_to_html
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
