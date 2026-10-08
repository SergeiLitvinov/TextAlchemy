"""Compatibility imports; document implementation lives in opendoc_model."""

from opendoc_model.diagnostics import (
    ConversionIssue as ConversionIssue,
)
from opendoc_model.diagnostics import (
    ConversionReport as ConversionReport,
)
from opendoc_model.diagnostics import (
    IssueSeverity as IssueSeverity,
)

__all__ = ["ConversionIssue", "ConversionReport", "IssueSeverity"]
