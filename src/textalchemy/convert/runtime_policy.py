"""Application input suffix policy and optional route availability."""

import importlib.util
from pathlib import Path

from textalchemy.core.types import DocFormat

_MODULE_REQUIREMENTS = {
    "python-docx": "docx",
    "python-pptx": "pptx",
    "pymupdf": "fitz",
    "beautifulsoup4": "bs4",
}


def requirement_available(requirement: str) -> bool:
    if requirement == "djvutxt":
        from shutil import which

        return which("djvutxt") is not None
    if requirement == "libreoffice":
        from opendoc_formats.office import find_libreoffice

        return find_libreoffice() is not None
    module = _MODULE_REQUIREMENTS.get(requirement, requirement.replace("-", "_"))
    return importlib.util.find_spec(module) is not None



def infer_format(path: str | Path) -> DocFormat:
    from textalchemy.convert.input_policy import WORKBOOK_EXTENSIONS, WORKBOOK_MESSAGE

    suffix = Path(path).suffix.lower()
    if suffix in WORKBOOK_EXTENSIONS:
        raise ValueError(WORKBOOK_MESSAGE)
    aliases = {
        ".pdf": DocFormat.PDF,
        ".docx": DocFormat.DOCX,
        ".pptx": DocFormat.PPTX,
        ".html": DocFormat.HTML,
        ".htm": DocFormat.HTML,
        ".tex": DocFormat.LATEX,
        ".json": DocFormat.MODEL,
        ".txt": DocFormat.TXT,
        ".djvu": DocFormat.DJVU,
        ".epub": DocFormat.EPUB,
    }
    if suffix not in aliases:
        raise ValueError(f"cannot infer document format from suffix {suffix or '<none>'!r}")
    return aliases[suffix]
