"""Типизированные контракты стадий конверсионного конвейера."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol, TypeAlias, runtime_checkable

from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import DocumentModel

StageValue: TypeAlias = Path | DocumentModel
CancellationCheck: TypeAlias = Callable[[], bool]


class StageKind(str, Enum):
    """Стабильные этапы преобразования документа."""

    PARSE = "parse"
    NORMALIZE = "normalize"
    LAYOUT = "layout"
    RESOURCES = "resources"
    SERIALIZE = "serialize"
    VERIFY = "verify"


@dataclass(frozen=True)
class StageContext:
    """Контекст выполнения, не зависящий от HTTP или конкретного формата."""

    output_path: Path
    cancelled: CancellationCheck = field(default=lambda: False, compare=False, repr=False)


@dataclass(frozen=True)
class StageResult:
    """Значение и диагностика после одной стадии."""

    value: StageValue
    report: ConversionReport | None = None


@runtime_checkable
class ConversionStage(Protocol):
    """Порт отдельной стадии для infrastructure-адаптера."""

    id: str
    kind: StageKind

    def execute(self, value: StageValue, context: StageContext) -> StageResult:
        ...


@dataclass(frozen=True)
class FormatExtension:
    """Изолированные данные формата внутри namespaced extension-map."""

    namespace: str
    values: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.namespace or "." in self.namespace:
            raise ValueError("namespace расширения должен быть непустым простым идентификатором")

    def apply_to(self, properties: dict[str, Any]) -> dict[str, Any]:
        return {**properties, self.namespace: dict(self.values)}

    @classmethod
    def from_properties(cls, properties: Any, namespace: str) -> FormatExtension | None:
        if not isinstance(properties, dict):
            return None
        values = properties.get(namespace)
        return cls(namespace, dict(values)) if isinstance(values, dict) else None


__all__ = [
    "CancellationCheck",
    "ConversionStage",
    "FormatExtension",
    "StageContext",
    "StageKind",
    "StageResult",
    "StageValue",
]
