"""Shared font preflight for model exporters."""

from __future__ import annotations

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import DocumentModel
from textalchemy.fonts import FontResolver, prepare_document_fonts


def prepare_fonts(document: DocumentModel, report: ConversionReport) -> DocumentModel:
    prepared, font_report = prepare_document_fonts(document, FontResolver.system())
    report.metrics["font_resolution"] = font_report.to_dict()
    for resolution in font_report.substitutions:
        if resolution.path is None:
            report.add(
                IssueSeverity.LOSS,
                "font-unavailable",
                f"font {resolution.requested!r} is unavailable and no deterministic substitute was found",
            )
        else:
            report.add(
                IssueSeverity.WARNING,
                "font-substitution",
                f"font {resolution.requested!r} replaced by {resolution.resolved!r} (distance {resolution.metric_distance:.3f})",
            )
    for resolution in font_report.resolutions.values():
        if resolution.path is not None and not resolution.embeddable:
            report.add(
                IssueSeverity.WARNING,
                "font-embedding-license",
                f"font {resolution.resolved!r} has restricted embedding flags",
            )
        elif resolution.path is not None and not resolution.subsettable:
            report.add(
                IssueSeverity.WARNING,
                "font-subsetting-license",
                f"font {resolution.resolved!r} forbids subsetting and will be embedded in full",
            )
        if resolution.missing_glyphs:
            sample = "".join(resolution.missing_glyphs[:12])
            report.add(
                IssueSeverity.LOSS,
                "font-glyphs",
                f"font {resolution.resolved!r} misses {len(resolution.missing_glyphs)} glyph(s): {sample}",
            )
    return prepared


__all__ = ["prepare_fonts"]
