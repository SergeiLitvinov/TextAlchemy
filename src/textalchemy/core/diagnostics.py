"""Compatibility imports; document implementation lives in opendoc."""

from opendoc.diagnostics import (
    ConversionIssue as ConversionIssue,
)
from opendoc.diagnostics import (
    ConversionReport as ConversionReport,
)
from opendoc.diagnostics import (
    IssueSeverity as IssueSeverity,
)

__all__ = ["ConversionIssue", "ConversionReport", "IssueSeverity"]
