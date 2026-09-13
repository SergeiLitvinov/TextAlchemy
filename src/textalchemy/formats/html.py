"""Lazy public HTML readers."""

from pathlib import Path

from textalchemy.core.document_adapters import document_to_text
from textalchemy.core.types import DocFormat, Text


def read_html_model(path: str | Path, *, resource_root: str | Path | None = None):
    from textalchemy.formats.html_model import read_html_model as read_model

    return read_model(path, resource_root=resource_root)


def read_html(path: str | Path) -> Text:
    try:
        model = read_html_model(path)
    except ImportError:
        return Text(source_format=DocFormat.HTML, engine="bs4+tinycss2", warnings=["Install textalchemy[html]"])
    result = document_to_text(model)
    result.warnings.extend(item["message"] for item in model.metadata["html"]["warnings"])
    return result
