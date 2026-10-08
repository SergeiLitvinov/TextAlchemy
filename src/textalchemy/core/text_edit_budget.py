"""Compatibility alias: limits and implementation have one owner."""

import sys

from opendoc_model import text_edit_budget as _implementation

sys.modules[__name__] = _implementation
