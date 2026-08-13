"""Tests for the universal conversion capability graph."""

import pytest

from textalchemy.convert.capabilities import create_capability_registry
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


def test_builtin_registry_routes_docx_through_model_to_pdf():
    plan = create_capability_registry().plan(DocFormat.DOCX, DocFormat.PDF, mode=ConversionMode.FAITHFUL)

    assert plan is not None
    assert [step.id for step in plan.steps] == ["docx.model", "model.pdf"]
    assert plan.feature_support[DocumentFeature.TEXT] is FeatureSupport.EXACT
    assert plan.feature_support[DocumentFeature.PAGE_GEOMETRY] is FeatureSupport.VISUAL
    assert "reportlab" in plan.executable_requirements
    assert plan.preservation is not None
    assert plan.visual_score < 1.0
    assert plan.editability_score < plan.visual_score


def test_mode_selects_editable_or_visual_pdf_backend():
    registry = create_capability_registry()

    editable = registry.plan(
        DocFormat.PDF,
        DocFormat.DOCX,
        mode=ConversionMode.EDITABLE,
        features=[DocumentFeature.TEXT],
    )
    faithful = registry.plan(
        DocFormat.PDF,
        DocFormat.DOCX,
        mode=ConversionMode.FAITHFUL,
        features=[DocumentFeature.PAGE_GEOMETRY],
    )

    assert editable is not None and editable.steps[0].id == "pdf.docx.pdf2docx"
    assert faithful is not None and faithful.steps[0].id == "pdf.docx.pymupdf"


def test_planner_prefers_better_multistep_route():
    registry = CapabilityRegistry()
    modes = frozenset({ConversionMode.BALANCED})
    registry.register(
        ConverterCapabilities(
            "direct",
            DocFormat.DOCX,
            DocFormat.HTML,
            modes,
            {DocumentFeature.FORMULAS: FeatureSupport.UNSUPPORTED},
        )
    )
    registry.register(
        ConverterCapabilities(
            "decode",
            DocFormat.DOCX,
            DocFormat.MODEL,
            modes,
            {DocumentFeature.FORMULAS: FeatureSupport.EXACT},
        )
    )
    registry.register(
        ConverterCapabilities(
            "render",
            DocFormat.MODEL,
            DocFormat.HTML,
            modes,
            {DocumentFeature.FORMULAS: FeatureSupport.PARTIAL},
        )
    )

    plan = registry.plan(
        DocFormat.DOCX,
        DocFormat.HTML,
        features=[DocumentFeature.FORMULAS],
    )

    assert plan is not None
    assert [step.id for step in plan.steps] == ["decode", "render"]
    assert plan.feature_support[DocumentFeature.FORMULAS] is FeatureSupport.PARTIAL


def test_registry_rejects_duplicate_ids_and_reports_missing_route():
    registry = CapabilityRegistry()
    capabilities = ConverterCapabilities(
        "only",
        DocFormat.DOCX,
        DocFormat.MODEL,
        frozenset({ConversionMode.BALANCED}),
        {},
    )
    registry.register(capabilities)

    with pytest.raises(ValueError, match="duplicate"):
        registry.register(capabilities)
    assert registry.plan(DocFormat.PPTX, DocFormat.DOCX) is None


def test_preservation_profiles_compose_across_route():
    registry = CapabilityRegistry()
    modes = frozenset({ConversionMode.BALANCED})

    def profile(score):
        return PreservationProfile({dimension: score for dimension in PreservationDimension}, basis="test")

    registry.register(ConverterCapabilities("first", DocFormat.DOCX, DocFormat.MODEL, modes, {}, preservation=profile(0.9)))
    registry.register(ConverterCapabilities("second", DocFormat.MODEL, DocFormat.HTML, modes, {}, preservation=profile(0.8)))

    plan = registry.plan(DocFormat.DOCX, DocFormat.HTML)

    assert plan is not None and plan.preservation is not None
    assert plan.preservation.score(PreservationDimension.CONTENT) == pytest.approx(0.72)
    assert plan.visual_score == pytest.approx(0.72)
    assert plan.editability_score == pytest.approx(0.72)
    assert plan.lossless is False


def test_preservation_profile_validates_contract():
    with pytest.raises(ValueError, match="misses"):
        PreservationProfile({PreservationDimension.CONTENT: 1.0})
    with pytest.raises(ValueError, match="between 0 and 1"):
        PreservationProfile({dimension: 1.1 for dimension in PreservationDimension})
