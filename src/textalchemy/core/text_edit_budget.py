"""Compatibility alias: limits and implementation have one owner."""

import sys

from opendoc import text_edit_budget as _implementation

sys.modules[__name__] = _implementation
