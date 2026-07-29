"""Структурированная диагностика потерь и упрощений при конвертации."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    LOSS = "loss"
    ERROR = "error"


@dataclass(frozen=True)
class ConversionIssue:
    severity: IssueSeverity
    feature: str
    message: str
    location: str = ""


@dataclass
class ConversionReport:
    output_path: Path
    issues: list[ConversionIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return not any(issue.severity is IssueSeverity.ERROR for issue in self.issues)

    @property
    def lossless(self) -> bool:
        return self.success and not any(issue.severity is IssueSeverity.LOSS for issue in self.issues)

    def add(self, severity: IssueSeverity, feature: str, message: str, location: str = "") -> None:
        self.issues.append(ConversionIssue(severity, feature, message, location))

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "lossless": self.lossless,
            "output_path": str(self.output_path),
            "metrics": self.metrics,
            "issues": [
                {
                    "severity": issue.severity.value,
                    "feature": issue.feature,
                    "message": issue.message,
                    "location": issue.location,
                }
                for issue in self.issues
            ],
        }


__all__ = ["ConversionIssue", "ConversionReport", "IssueSeverity"]
