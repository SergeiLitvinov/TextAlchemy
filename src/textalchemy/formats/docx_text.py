"""Compatibility alias; implementation belongs to OpenDoc Formats."""
import sys
from importlib import import_module

sys.modules[__name__] = import_module('opendoc_formats.readers.docx_text')
