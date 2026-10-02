"""Compatibility alias: limits and implementation have one owner."""

import sys

from opendoc import text_flow as _implementation

sys.modules[__name__] = _implementation
