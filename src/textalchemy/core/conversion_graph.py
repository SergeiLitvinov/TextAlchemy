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

    @property
    def lossless(self) -> bool:
        return all(value is FeatureSupport.EXACT for value in self.feature_support.values())

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
            return ConversionPlan(source, target, mode, requested, (), 0.0, support)
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
                return ConversionPlan(source, target, mode, requested, steps, score, support)
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


__all__ = [
    "CapabilityRegistry",
    "ConversionPlan",
    "ConverterCapabilities",
    "DEFAULT_FEATURES",
    "DocumentFeature",
    "FeatureSupport",
]
