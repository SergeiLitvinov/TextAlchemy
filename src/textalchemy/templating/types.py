"""Values accepted and returned by the document template engine."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opendoc_model.document_model import FormulaFormat


@dataclass(frozen=True)
class TemplateImage:
    data: bytes | None = None
    source: str | Path | None = None
    media_type: str | None = None
    filename: str | None = None
    alt_text: str = ""
    width_pt: float | None = None
    height_pt: float | None = None


@dataclass(frozen=True)
class TemplateFormula:
    value: str
    format: FormulaFormat = FormulaFormat.LATEX
    fallback_text: str = ""
    display: bool = False


@dataclass
class TemplateInspection:
    references: dict[str, list[str]]
    errors: list[str]
    warnings: list[str]

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def required_variables(self) -> list[str]:
        return sorted(self.references)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "required_variables": self.required_variables,
            "references": self.references,
            "errors": self.errors,
            "warnings": self.warnings,
        }
