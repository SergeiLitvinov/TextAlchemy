"""Built-in conversion capabilities without importing heavy converter backends."""

from __future__ import annotations

from textalchemy.core.conversion_graph import (
    CapabilityRegistry,
    ConverterCapabilities,
    DocumentFeature,
    FeatureSupport,
)
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.types import DocFormat

S = FeatureSupport
ALL_MODES = frozenset(ConversionMode)


def _features(**values: FeatureSupport) -> dict[DocumentFeature, FeatureSupport]:
    return {DocumentFeature(name): value for name, value in values.items()}


def built_in_capabilities() -> tuple[ConverterCapabilities, ...]:
    return (
        ConverterCapabilities(
            "docx.model",
            DocFormat.DOCX,
            DocFormat.MODEL,
            ALL_MODES,
            _features(
                text=S.EXACT,
                styles=S.EXACT,
                raster_images=S.EXACT,
                vector_graphics=S.EXACT,
                formulas=S.EXACT,
                tables=S.EXACT,
                page_geometry=S.EXACT,
                sections=S.EXACT,
                running_content=S.EXACT,
                notes=S.EXACT,
                fields=S.EXACT,
            ),
            requirements=("python-docx", "lxml"),
            description="Rich DOCX importer",
        ),
        ConverterCapabilities(
            "model.docx",
            DocFormat.MODEL,
            DocFormat.DOCX,
            ALL_MODES,
            _features(
                text=S.EXACT,
                styles=S.EXACT,
                raster_images=S.EXACT,
                vector_graphics=S.EXACT,
                formulas=S.EXACT,
                tables=S.EXACT,
                page_geometry=S.EXACT,
                sections=S.EXACT,
                running_content=S.EXACT,
                notes=S.EXACT,
                fields=S.EXACT,
            ),
            requirements=("python-docx", "lxml"),
            description="Rich DOCX exporter",
        ),
        ConverterCapabilities(
            "model.html",
            DocFormat.MODEL,
            DocFormat.HTML,
            ALL_MODES,
            _features(
                text=S.EXACT,
                styles=S.EDITABLE,
                raster_images=S.EXACT,
                vector_graphics=S.EXACT,
                formulas=S.PARTIAL,
                tables=S.EDITABLE,
                page_geometry=S.VISUAL,
                sections=S.PARTIAL,
                running_content=S.PARTIAL,
                notes=S.PARTIAL,
                fields=S.PARTIAL,
            ),
            description="Self-contained HTML exporter",
        ),
        ConverterCapabilities(
            "model.pdf",
            DocFormat.MODEL,
            DocFormat.PDF,
            frozenset({ConversionMode.FAITHFUL, ConversionMode.BALANCED}),
            _features(
                text=S.EXACT,
                styles=S.VISUAL,
                raster_images=S.EXACT,
                vector_graphics=S.PARTIAL,
                formulas=S.PARTIAL,
                tables=S.VISUAL,
                page_geometry=S.VISUAL,
                sections=S.VISUAL,
                running_content=S.VISUAL,
                notes=S.PARTIAL,
                fields=S.VISUAL,
            ),
            requirements=("reportlab",),
            description="Portable PDF exporter",
        ),
        ConverterCapabilities(
            "pdf.docx.pdf2docx",
            DocFormat.PDF,
            DocFormat.DOCX,
            frozenset({ConversionMode.EDITABLE, ConversionMode.BALANCED}),
            _features(
                text=S.EDITABLE,
                styles=S.PARTIAL,
                raster_images=S.EDITABLE,
                vector_graphics=S.PARTIAL,
                formulas=S.PARTIAL,
                tables=S.PARTIAL,
                page_geometry=S.PARTIAL,
                sections=S.PARTIAL,
                running_content=S.PARTIAL,
                notes=S.UNSUPPORTED,
                fields=S.UNSUPPORTED,
            ),
            requirements=("pdf2docx",),
            description="Editable PDF to DOCX reconstruction",
        ),
        ConverterCapabilities(
            "pdf.docx.pymupdf",
            DocFormat.PDF,
            DocFormat.DOCX,
            frozenset({ConversionMode.FAITHFUL, ConversionMode.BALANCED}),
            _features(
                text=S.EDITABLE,
                styles=S.PARTIAL,
                raster_images=S.VISUAL,
                vector_graphics=S.VISUAL,
                formulas=S.VISUAL,
                tables=S.PARTIAL,
                page_geometry=S.PARTIAL,
                sections=S.PARTIAL,
                running_content=S.UNSUPPORTED,
                notes=S.UNSUPPORTED,
                fields=S.UNSUPPORTED,
            ),
            base_cost=2.0,
            requirements=("pymupdf", "python-docx"),
            description="Text extraction with raster page fallback",
        ),
        ConverterCapabilities(
            "pptx.html",
            DocFormat.PPTX,
            DocFormat.HTML,
            frozenset({ConversionMode.FAITHFUL, ConversionMode.BALANCED}),
            _features(
                text=S.EDITABLE,
                styles=S.VISUAL,
                raster_images=S.EXACT,
                vector_graphics=S.EXACT,
                formulas=S.EXACT,
                tables=S.VISUAL,
                page_geometry=S.EXACT,
                sections=S.VISUAL,
                running_content=S.UNSUPPORTED,
                notes=S.UNSUPPORTED,
                fields=S.PARTIAL,
            ),
            requirements=("python-pptx", "lxml"),
            description="Self-contained PPTX slide viewer",
        ),
        ConverterCapabilities(
            "docx.latex",
            DocFormat.DOCX,
            DocFormat.LATEX,
            frozenset({ConversionMode.EDITABLE, ConversionMode.BALANCED}),
            _features(
                text=S.EDITABLE,
                styles=S.PARTIAL,
                raster_images=S.UNSUPPORTED,
                vector_graphics=S.UNSUPPORTED,
                formulas=S.PARTIAL,
                tables=S.EDITABLE,
                page_geometry=S.UNSUPPORTED,
                sections=S.PARTIAL,
                running_content=S.UNSUPPORTED,
                notes=S.UNSUPPORTED,
                fields=S.PARTIAL,
            ),
            requirements=("python-docx",),
            description="Semantic DOCX to LaTeX converter",
        ),
    )


def create_capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for capabilities in built_in_capabilities():
        registry.register(capabilities)
    return registry


__all__ = ["built_in_capabilities", "create_capability_registry"]
