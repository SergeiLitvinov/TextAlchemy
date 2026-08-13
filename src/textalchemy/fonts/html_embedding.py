"""Target-specific embedding of resolved fonts into self-contained HTML."""

from __future__ import annotations

import base64
from pathlib import Path

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import DocumentModel
from textalchemy.fonts.embedding import collect_font_usages, subset_font

_MIME_TYPES = {".ttf": "font/ttf", ".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2"}


def embedded_font_stylesheet(
    document: DocumentModel, report: ConversionReport, *, target: str = "html", subset_fonts: bool = False
) -> str:
    """Return deterministic ``@font-face`` rules for resolved, embeddable fonts."""
    payload = document.metadata.get("font_resolution", {})
    resolutions = payload.get("resolutions", {}) if isinstance(payload, dict) else {}
    rules: list[str] = []
    embedded: set[tuple[str, str, int, bool]] = set()
    total_bytes = 0
    embedded_bytes = 0
    usage_by_identity = {
        (usage.family.casefold(), str(usage.path).casefold(), 700 if usage.bold else 400, usage.italic): usage
        for usage in collect_font_usages(document)
    }

    for key, resolution in sorted(resolutions.items()):
        if not isinstance(resolution, dict) or not resolution.get("path"):
            continue
        path = Path(str(resolution["path"]))
        family = str(resolution.get("resolved") or path.stem)
        _, bold, italic = _resolution_key_parts(str(key))
        identity = (family.casefold(), str(path).casefold(), bold, italic)
        if identity in embedded:
            continue
        if not resolution.get("embeddable", False):
            continue
        suffix = path.suffix.casefold()
        mime = _MIME_TYPES.get(suffix)
        try:
            source_data = path.read_bytes()
            usage = usage_by_identity.get(identity)
            data = subset_font(usage) if subset_fonts and usage is not None else source_data
        except OSError as error:
            report.add(IssueSeverity.WARNING, "font-embedding-read", f"cannot embed font {family!r}: {error}")
            continue
        if not mime:
            report.add(
                IssueSeverity.WARNING,
                "font-embedding-format",
                f"font format {suffix or '<unknown>'} is not embeddable in HTML",
            )
            continue
        encoded = base64.b64encode(data).decode("ascii")
        escaped_family = family.replace("\\", "\\\\").replace('"', '\\"')
        rules.append(
            f'@font-face {{ font-family: "{escaped_family}"; src: url("data:{mime};base64,{encoded}") '
            f'format("{suffix.removeprefix(".")}"); font-weight: {bold}; font-style: {"italic" if italic else "normal"}; }}'
        )
        embedded.add(identity)
        total_bytes += len(source_data)
        embedded_bytes += len(data)

    report.metrics["font_embedding"] = {
        "embedded_faces": len(embedded),
        "source_bytes": total_bytes,
        "embedded_bytes": embedded_bytes,
        "target": target,
    }
    return "\n".join(rules)


def archived_font_stylesheet(document: DocumentModel, workspace: object, report: ConversionReport) -> str:
    """Write font subsets into an artifact archive and return relative @font-face rules."""
    rules: list[str] = []
    source_bytes = embedded_bytes = 0
    embedded = 0
    for index, usage in enumerate(collect_font_usages(document), start=1):
        if not usage.embeddable:
            continue
        try:
            source_size = usage.path.stat().st_size
            data = subset_font(usage)
            suffix = usage.path.suffix.casefold()
            if suffix not in _MIME_TYPES:
                continue
            filename = f"font-{index}{suffix}"
            workspace.write_bytes(filename, data, fallback="font.ttf")
        except OSError as error:
            report.add(IssueSeverity.WARNING, "font-embedding-read", f"cannot embed font {usage.family!r}: {error}")
            continue
        family = usage.family.replace("\\", "\\\\").replace('"', '\\"')
        rules.append(
            f'@font-face {{ font-family: "{family}"; src: url("{filename}"); '
            f'font-weight: {700 if usage.bold else 400}; font-style: {"italic" if usage.italic else "normal"}; }}'
        )
        embedded += 1
        source_bytes += source_size
        embedded_bytes += len(data)
    report.metrics["font_embedding"] = {
        "embedded_faces": embedded,
        "source_bytes": source_bytes,
        "embedded_bytes": embedded_bytes,
        "target": "pdf",
    }
    return "\n".join(rules)


def _resolution_key_parts(key: str) -> tuple[str, int, bool]:
    family, separator, flags = key.rpartition("|")
    if not separator:
        return key, 400, False
    family, separator, bold = family.rpartition("|")
    if not separator:
        return key, 400, flags == "1"
    return family, 700 if bold == "1" else 400, flags == "1"


__all__ = ["archived_font_stylesheet", "embedded_font_stylesheet"]
