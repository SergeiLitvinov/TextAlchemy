"""Built-in conversion capabilities without importing heavy converter backends."""

from __future__ import annotations

from textalchemy.core.conversion_graph import (
    CapabilityRegistry,
    ConverterCapabilities,
    DocumentFeature,
    FeatureSupport,
    PreservationDimension,
    PreservationProfile,
)
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.types import DocFormat

S = FeatureSupport
ALL_MODES = frozenset(ConversionMode)


def _features(**values: FeatureSupport) -> dict[DocumentFeature, FeatureSupport]:
    return {DocumentFeature(name): value for name, value in values.items()}


def _profile(
    *, content: float, semantics: float, geometry: float, style: float, relationships: float, editability: float
) -> PreservationProfile:
    values = locals()
    return PreservationProfile(
        {dimension: values[dimension.value] for dimension in PreservationDimension},
        basis="engine-contract-v1",
    )


def built_in_capabilities() -> tuple[ConverterCapabilities, ...]:
    return (
        ConverterCapabilities(
            "html.model", DocFormat.HTML, DocFormat.MODEL,
            frozenset({ConversionMode.BALANCED, ConversionMode.EDITABLE}),
            _features(text=S.EDITABLE, styles=S.PARTIAL, tables=S.EDITABLE, formulas=S.PARTIAL,
                      raster_images=S.PARTIAL, vector_graphics=S.PARTIAL, sections=S.PARTIAL),
            requirements=("beautifulsoup4", "tinycss2"),
            description="Static HTML, basic CSS, tables, lists, embedded SVG and MathML; no external loads",
        ),
        ConverterCapabilities(
            "model.txt",
            DocFormat.MODEL,
            DocFormat.TXT,
            frozenset({ConversionMode.BALANCED, ConversionMode.EDITABLE}),
            _features(text=S.EXACT, tables=S.PARTIAL, formulas=S.PARTIAL, sections=S.PARTIAL),
            description="UTF-8 plain text exporter with flattening diagnostics",
        ),
        ConverterCapabilities(
            "txt.model",
            DocFormat.TXT,
            DocFormat.MODEL,
            ALL_MODES,
            _features(text=S.EXACT),
            description="Plain text lines as editable paragraphs",
        ),
        ConverterCapabilities(
            "epub.model",
            DocFormat.EPUB,
            DocFormat.MODEL,
            ALL_MODES,
            _features(text=S.EXACT, styles=S.EDITABLE, raster_images=S.EXACT, vector_graphics=S.EXACT, sections=S.EDITABLE),
            requirements=("ebooklib", "beautifulsoup4"),
            description="EPUB spine, links, media, and basic CSS as an editable model",
        ),
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
            preservation=_profile(content=1.0, semantics=0.98, geometry=0.97, style=0.98, relationships=0.97, editability=1.0),
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
            preservation=_profile(content=1.0, semantics=0.98, geometry=0.96, style=0.98, relationships=0.96, editability=1.0),
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
            preservation=_profile(content=0.99, semantics=0.90, geometry=0.91, style=0.94, relationships=0.88, editability=0.86),
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
            requirements=("pymupdf",),
            description="Portable PDF exporter",
            preservation=_profile(content=0.99, semantics=0.65, geometry=0.94, style=0.94, relationships=0.70, editability=0.20),
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
            preservation=_profile(content=0.92, semantics=0.72, geometry=0.74, style=0.72, relationships=0.48, editability=0.82),
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
            preservation=_profile(content=0.92, semantics=0.60, geometry=0.91, style=0.88, relationships=0.35, editability=0.44),
        ),
        ConverterCapabilities(
            "pptx.model",
            DocFormat.PPTX,
            DocFormat.MODEL,
            ALL_MODES,
            _features(
                text=S.EXACT,
                styles=S.EDITABLE,
                raster_images=S.EXACT,
                vector_graphics=S.PARTIAL,
                formulas=S.EXACT,
                tables=S.EXACT,
                page_geometry=S.EXACT,
                sections=S.EXACT,
                running_content=S.UNSUPPORTED,
                notes=S.EXACT,
                fields=S.PARTIAL,
            ),
            requirements=("python-pptx", "lxml"),
            description="Rich PPTX importer",
            preservation=_profile(content=0.99, semantics=0.94, geometry=0.98, style=0.95, relationships=0.88, editability=0.96),
        ),
        ConverterCapabilities(
            "model.pptx",
            DocFormat.MODEL,
            DocFormat.PPTX,
            frozenset({ConversionMode.EDITABLE, ConversionMode.BALANCED}),
            _features(
                text=S.EDITABLE,
                styles=S.PARTIAL,
                raster_images=S.EDITABLE,
                vector_graphics=S.PARTIAL,
                formulas=S.PARTIAL,
                tables=S.EDITABLE,
                page_geometry=S.PARTIAL,
                sections=S.EDITABLE,
                notes=S.EDITABLE,
                running_content=S.UNSUPPORTED,
                fields=S.UNSUPPORTED,
            ),
            requirements=("python-pptx", "lxml"),
            description="Editable PPTX exporter; native objects, partial formatting, no source package preservation",
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
            base_cost=3.0,
            requirements=("python-pptx", "lxml"),
            description="Self-contained PPTX slide viewer (legacy direct renderer)",
            preservation=_profile(content=0.98, semantics=0.72, geometry=0.98, style=0.96, relationships=0.66, editability=0.42),
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
            preservation=_profile(content=0.94, semantics=0.86, geometry=0.30, style=0.62, relationships=0.58, editability=0.90),
        ),
    )


def create_capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for capabilities in built_in_capabilities():
        registry.register(capabilities)
    return registry


__all__ = ["built_in_capabilities", "create_capability_registry"]
