"""Compatibility alias: limits and implementation have one owner."""

import sys

from opendoc import emphasis_quality as _implementation

sys.modules[__name__] = _implementation
