"""Capability model and route planner for document conversions."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from enum import Enum
from itertools import count
from typing import Callable, Iterable, Mapping

from textalchemy.core.document_model import ConversionMode
from textalchemy.core.types import DocFormat


class DocumentFeature(str, Enum):
    TEXT = "text"
    STYLES = "styles"
    RASTER_IMAGES = "raster_images"
    VECTOR_GRAPHICS = "vector_graphics"
    FORMULAS = "formulas"
    TABLES = "tables"
    PAGE_GEOMETRY = "page_geometry"
    SECTIONS = "sections"
    RUNNING_CONTENT = "running_content"
    NOTES = "notes"
    FIELDS = "fields"


class FeatureSupport(str, Enum):
    EXACT = "exact"
    EDITABLE = "editable"
    VISUAL = "visual"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class PreservationDimension(str, Enum):
    CONTENT = "content"
    SEMANTICS = "semantics"
    GEOMETRY = "geometry"
    STYLE = "style"
    RELATIONSHIPS = "relationships"
    EDITABILITY = "editability"


@dataclass(frozen=True)
class PreservationProfile:
    """Estimated 0..1 retention for independent qualities of a conversion edge."""

    scores: Mapping[PreservationDimension, float]
    basis: str = "declared"

    def __post_init__(self) -> None:
        missing = set(PreservationDimension) - set(self.scores)
        if missing:
            raise ValueError(f"preservation profile misses: {', '.join(sorted(item.value for item in missing))}")
        invalid = {item.value: value for item, value in self.scores.items() if not 0.0 <= value <= 1.0}
        if invalid:
            raise ValueError(f"preservation scores must be between 0 and 1: {invalid}")

    def score(self, dimension: PreservationDimension) -> float:
        return self.scores[dimension]

    def to_dict(self) -> dict[str, object]:
        return {
            "basis": self.basis,
            "scores": {dimension.value: round(self.score(dimension), 4) for dimension in PreservationDimension},
        }


DEFAULT_FEATURES = frozenset(DocumentFeature)

_SUPPORT_RANK = {
    FeatureSupport.EXACT: 0,
    FeatureSupport.EDITABLE: 1,
    FeatureSupport.VISUAL: 2,
    FeatureSupport.PARTIAL: 3,
    FeatureSupport.UNSUPPORTED: 4,
}

_MODE_PENALTIES = {
    ConversionMode.EDITABLE: {
        FeatureSupport.EXACT: 0.0,
        FeatureSupport.EDITABLE: 0.25,
        FeatureSupport.VISUAL: 3.0,
        FeatureSupport.PARTIAL: 5.0,
        FeatureSupport.UNSUPPORTED: 100.0,
    },
    ConversionMode.FAITHFUL: {
        FeatureSupport.EXACT: 0.0,
        FeatureSupport.EDITABLE: 1.5,
        FeatureSupport.VISUAL: 0.25,
        FeatureSupport.PARTIAL: 5.0,
        FeatureSupport.UNSUPPORTED: 100.0,
    },
    ConversionMode.BALANCED: {
        FeatureSupport.EXACT: 0.0,
        FeatureSupport.EDITABLE: 0.5,
        FeatureSupport.VISUAL: 0.75,
        FeatureSupport.PARTIAL: 3.0,
        FeatureSupport.UNSUPPORTED: 100.0,
    },
}


@dataclass(frozen=True)
class ConverterCapabilities:
    id: str
    source: DocFormat
    target: DocFormat
    modes: frozenset[ConversionMode]
    features: Mapping[DocumentFeature, FeatureSupport]
    base_cost: float = 1.0
    requirements: tuple[str, ...] = ()
    description: str = ""
    preservation: PreservationProfile | None = None

    def support_for(self, feature: DocumentFeature) -> FeatureSupport:
        return self.features.get(feature, FeatureSupport.UNSUPPORTED)

    def cost(self, mode: ConversionMode, features: Iterable[DocumentFeature]) -> float:
        penalties = _MODE_PENALTIES[mode]
        return self.base_cost + sum(penalties[self.support_for(feature)] for feature in features)


@dataclass(frozen=True)
class ConversionPlan:
    source: DocFormat
    target: DocFormat
    mode: ConversionMode
    requested_features: frozenset[DocumentFeature]
    steps: tuple[ConverterCapabilities, ...]
    score: float
    feature_support: Mapping[DocumentFeature, FeatureSupport] = field(default_factory=dict)
    preservation: PreservationProfile | None = None

    @property
    def lossless(self) -> bool:
        return bool(self.preservation) and all(value >= 0.999 for value in self.preservation.scores.values())

    @property
    def visual_score(self) -> float:
        if not self.preservation:
            return 0.0
        values = [
            self.preservation.score(PreservationDimension.CONTENT),
            self.preservation.score(PreservationDimension.GEOMETRY),
            self.preservation.score(PreservationDimension.STYLE),
        ]
        return sum(values) / len(values)

    @property
    def editability_score(self) -> float:
        return self.preservation.score(PreservationDimension.EDITABILITY) if self.preservation else 0.0

    @property
    def executable_requirements(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(requirement for step in self.steps for requirement in step.requirements))

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source.value,
            "target": self.target.value,
            "mode": self.mode.value,
            "score": round(self.score, 3),
            "lossless": self.lossless,
            "visual_score": round(self.visual_score, 4),
            "editability_score": round(self.editability_score, 4),
            "preservation": self.preservation.to_dict() if self.preservation else None,
            "requested_features": sorted(feature.value for feature in self.requested_features),
            "feature_support": {
                feature.value: self.feature_support[feature].value
                for feature in sorted(self.feature_support, key=lambda item: item.value)
            },
            "requirements": list(self.executable_requirements),
            "steps": [
                {
                    "id": step.id,
                    "source": step.source.value,
                    "target": step.target.value,
                    "description": step.description,
                    "requirements": list(step.requirements),
                }
                for step in self.steps
            ],
        }


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: dict[str, ConverterCapabilities] = {}

    def register(self, capabilities: ConverterCapabilities) -> None:
        if capabilities.id in self._items:
            raise ValueError(f"duplicate converter capability id: {capabilities.id}")
        if not capabilities.modes:
            raise ValueError(f"converter {capabilities.id!r} must support at least one mode")
        self._items[capabilities.id] = capabilities

    def all(self) -> tuple[ConverterCapabilities, ...]:
        return tuple(self._items.values())

    def find(
        self,
        source: DocFormat,
        target: DocFormat,
        *,
        mode: ConversionMode | None = None,
    ) -> tuple[ConverterCapabilities, ...]:
        return tuple(
            item
            for item in self._items.values()
            if item.source is source
            and item.target is target
            and (mode is None or mode in item.modes)
        )

    def plan(
        self,
        source: DocFormat,
        target: DocFormat,
        *,
        mode: ConversionMode = ConversionMode.BALANCED,
        features: Iterable[DocumentFeature] = DEFAULT_FEATURES,
        max_steps: int = 4,
        available: Callable[[ConverterCapabilities], bool] | None = None,
    ) -> ConversionPlan | None:
        requested = frozenset(features)
        if source is target:
            support = {feature: FeatureSupport.EXACT for feature in requested}
            return ConversionPlan(source, target, mode, requested, (), 0.0, support, _identity_profile())
        if max_steps < 1:
            return None

        serial = count()
        queue: list[tuple[float, int, DocFormat, tuple[ConverterCapabilities, ...]]] = [
            (0.0, next(serial), source, ())
        ]
        best: dict[tuple[DocFormat, int], float] = {(source, 0): 0.0}
        while queue:
            score, _, current, steps = heapq.heappop(queue)
            if current is target:
                support = _compose_support(steps, requested)
                return ConversionPlan(source, target, mode, requested, steps, score, support, _compose_preservation(steps))
            if len(steps) >= max_steps:
                continue
            visited_formats = {source, *(step.target for step in steps)}
            for edge in self._items.values():
                if (
                    edge.source is not current
                    or mode not in edge.modes
                    or edge.target in visited_formats
                    or (available is not None and not available(edge))
                ):
                    continue
                new_steps = (*steps, edge)
                new_score = score + edge.cost(mode, requested)
                state = (edge.target, len(new_steps))
                if new_score >= best.get(state, float("inf")):
                    continue
                best[state] = new_score
                heapq.heappush(queue, (new_score, next(serial), edge.target, new_steps))
        return None


def _compose_support(
    steps: tuple[ConverterCapabilities, ...],
    features: frozenset[DocumentFeature],
) -> dict[DocumentFeature, FeatureSupport]:
    return {
        feature: max((step.support_for(feature) for step in steps), key=_SUPPORT_RANK.__getitem__)
        for feature in features
    }


def _identity_profile() -> PreservationProfile:
    return PreservationProfile({dimension: 1.0 for dimension in PreservationDimension}, basis="identity")


def _legacy_profile(capabilities: ConverterCapabilities) -> PreservationProfile:
    values = {
        FeatureSupport.EXACT: 1.0,
        FeatureSupport.EDITABLE: 0.9,
        FeatureSupport.VISUAL: 0.75,
        FeatureSupport.PARTIAL: 0.5,
        FeatureSupport.UNSUPPORTED: 0.0,
    }
    feature_values = [values[capabilities.support_for(feature)] for feature in DocumentFeature]
    mean = sum(feature_values) / len(feature_values)
    editable = sum(
        values[capabilities.support_for(feature)]
        for feature in (DocumentFeature.TEXT, DocumentFeature.TABLES, DocumentFeature.FORMULAS, DocumentFeature.FIELDS)
    ) / 4
    return PreservationProfile(
        {dimension: editable if dimension is PreservationDimension.EDITABILITY else mean for dimension in PreservationDimension},
        basis="legacy-feature-support",
    )


def _compose_preservation(steps: tuple[ConverterCapabilities, ...]) -> PreservationProfile:
    profiles = [step.preservation or _legacy_profile(step) for step in steps]
    return PreservationProfile(
        {
            dimension: round(_product(profile.score(dimension) for profile in profiles), 6)
            for dimension in PreservationDimension
        },
        basis="composed-edge-profiles",
    )


def _product(values: Iterable[float]) -> float:
    result = 1.0
    for value in values:
        result *= value
    return result


__all__ = [
    "CapabilityRegistry",
    "ConversionPlan",
    "ConverterCapabilities",
    "DEFAULT_FEATURES",
    "DocumentFeature",
    "FeatureSupport",
    "PreservationDimension",
    "PreservationProfile",
]
