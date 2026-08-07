"""Структурная инспекция документов и промежуточной модели."""

from __future__ import annotations

import base64
import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from textalchemy.core.diagnostics import ConversionIssue, IssueSeverity
from textalchemy.core.document_model import (
    Block,
    Box,
    DocumentModel,
    Formula,
    Image,
    PageSettings,
    Paragraph,
    Resource,
    Table,
    TextRun,
)
from textalchemy.core.exceptions import TextAlchemyError


@dataclass
class DocumentInspection:
    source_path: Path | None
    source_format: str
    metadata: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, int] = field(default_factory=dict)
    pages: list[dict[str, Any]] = field(default_factory=list)
    resources: list[dict[str, Any]] = field(default_factory=list)
    package_parts: list[dict[str, Any]] = field(default_factory=list)
    fonts: dict[str, int] = field(default_factory=dict)
    formula_formats: dict[str, int] = field(default_factory=dict)
    issues: list[ConversionIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(issue.severity is IssueSeverity.ERROR for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(issue.severity in {IssueSeverity.WARNING, IssueSeverity.LOSS} for issue in self.issues)

    def add(self, severity: IssueSeverity, feature: str, message: str, location: str = "") -> None:
        self.issues.append(ConversionIssue(severity, feature, message, location))

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "source_path": str(self.source_path) if self.source_path is not None else None,
            "source_format": self.source_format,
            "metadata": _json_safe(self.metadata),
            "metrics": self.metrics,
            "pages": self.pages,
            "resources": self.resources,
            "package_parts": self.package_parts,
            "fonts": self.fonts,
            "formula_formats": self.formula_formats,
            "issues": [
                {
                    "severity": issue.severity.value,
                    "feature": issue.feature,
                    "message": issue.message,
                    "location": issue.location,
                }
                for issue in self.issues
            ],
        }


@dataclass
class DocumentComparison:
    source: DocumentInspection
    target: DocumentInspection
    retention: dict[str, dict[str, float | int]]
    page_geometry: list[dict[str, Any]]
    geometry_summary: dict[str, float | int]
    resource_comparison: dict[str, Any]
    package_comparison: dict[str, Any]
    font_comparison: dict[str, Any]
    matching_resource_hashes: int
    matching_package_part_hashes: int
    issues: list[ConversionIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.source.valid and self.target.valid

    @property
    def has_losses(self) -> bool:
        return any(issue.severity is IssueSeverity.LOSS for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "has_losses": self.has_losses,
            "retention": self.retention,
            "page_geometry": self.page_geometry,
            "geometry_summary": self.geometry_summary,
            "resource_comparison": self.resource_comparison,
            "package_comparison": self.package_comparison,
            "font_comparison": self.font_comparison,
            "matching_resource_hashes": self.matching_resource_hashes,
            "matching_package_part_hashes": self.matching_package_part_hashes,
            "issues": [
                {
                    "severity": issue.severity.value,
                    "feature": issue.feature,
                    "message": issue.message,
                    "location": issue.location,
                }
                for issue in self.issues
            ],
        }


def compare_inspections(source: DocumentInspection, target: DocumentInspection) -> DocumentComparison:
    """Сравнить структурную сохранность двух проинспектированных документов."""

    source_metrics = _quality_metrics(source)
    target_metrics = _quality_metrics(target)
    retention: dict[str, dict[str, float | int]] = {}
    issues: list[ConversionIssue] = []
    for name in source_metrics:
        before = source_metrics[name]
        after = target_metrics[name]
        ratio = 1.0 if before == 0 else min(after / before, 1.0)
        retention[name] = {
            "source": before,
            "target": after,
            "delta": after - before,
            "ratio": round(ratio, 4),
        }
        if after < before:
            issues.append(
                ConversionIssue(
                    IssueSeverity.LOSS,
                    f"retention-{name}",
                    f"{name}: retained {after} of {before}",
                )
            )

    page_geometry, geometry_summary, geometry_issues = _compare_page_geometry(source.pages, target.pages)
    issues.extend(geometry_issues)
    resource_comparison, resource_issues = _compare_resources(source.resources, target.resources)
    issues.extend(resource_issues)
    package_comparison, package_issues = _compare_resources(source.package_parts, target.package_parts)
    issues.extend(
        ConversionIssue(issue.severity, "package-part-loss", issue.message.replace("resource", "package part"))
        for issue in package_issues
    )
    font_comparison, font_issues = _compare_fonts(source.fonts, target.fonts)
    issues.extend(font_issues)
    return DocumentComparison(
        source=source,
        target=target,
        retention=retention,
        page_geometry=page_geometry,
        geometry_summary=geometry_summary,
        resource_comparison=resource_comparison,
        package_comparison=package_comparison,
        font_comparison=font_comparison,
        matching_resource_hashes=resource_comparison["exact_hash_matches"],
        matching_package_part_hashes=package_comparison["exact_hash_matches"],
        issues=issues,
    )


def _compare_page_geometry(
    source_pages: list[dict[str, Any]],
    target_pages: list[dict[str, Any]],
    *,
    tolerance_pt: float = 0.5,
) -> tuple[list[dict[str, Any]], dict[str, float | int], list[ConversionIssue]]:
    if not source_pages or not target_pages:
        issues: list[ConversionIssue] = []
        if source_pages and not target_pages:
            issues.append(
                ConversionIssue(
                    IssueSeverity.WARNING,
                    "page-geometry-n-a",
                    "target has no page geometry (pagination-less format, e.g. HTML/LaTeX)",
                    "pages",
                )
            )
        elif target_pages and not source_pages:
            issues.append(
                ConversionIssue(
                    IssueSeverity.WARNING,
                    "page-geometry-n-a",
                    "source has no page geometry",
                    "pages",
                )
            )
        summary: dict[str, float | int] = {
            "source_pages": len(source_pages),
            "target_pages": len(target_pages),
            "compared_pages": 0,
            "missing_pages": abs(len(source_pages) - len(target_pages)),
            "tolerance_pt": tolerance_pt,
            "max_dimension_error_pt": 0.0,
            "mean_dimension_error_pt": 0.0,
            "rms_dimension_error_pt": 0.0,
            "max_margin_error_pt": 0.0,
            "mean_margin_error_pt": 0.0,
            "rms_margin_error_pt": 0.0,
        }
        return [], summary, issues
    page_geometry: list[dict[str, Any]] = []
    issues: list[ConversionIssue] = []
    dimension_errors: list[float] = []
    margin_errors: list[float] = []
    missing_pages = 0
    margin_names = ("margin_top_pt", "margin_right_pt", "margin_bottom_pt", "margin_left_pt")
    for index in range(max(len(source_pages), len(target_pages))):
        source_page = source_pages[index] if index < len(source_pages) else None
        target_page = target_pages[index] if index < len(target_pages) else None
        if source_page is None or target_page is None:
            missing_pages += 1
            page_geometry.append(
                {
                    "index": index,
                    "source": source_page,
                    "target": target_page,
                    "same_size": False,
                    "same_margins": False,
                    "same_geometry": False,
                }
            )
            issues.append(
                ConversionIssue(
                    IssueSeverity.LOSS,
                    "page-geometry",
                    f"page {index + 1} exists only in {'target' if source_page is None else 'source'}",
                    f"pages[{index}]",
                )
            )
            continue
        width_delta = float(target_page["width_pt"]) - float(source_page["width_pt"])
        height_delta = float(target_page["height_pt"]) - float(source_page["height_pt"])
        dimension_error = math.hypot(width_delta, height_delta)
        max_dimension_error = max(abs(width_delta), abs(height_delta))
        dimension_errors.append(dimension_error)
        same_size = max_dimension_error <= tolerance_pt
        margin_deltas = {
            name.removesuffix("_pt") + "_delta_pt": round(float(target_page[name]) - float(source_page[name]), 3)
            for name in margin_names
            if name in source_page and name in target_page
        }
        current_margin_errors = [abs(float(value)) for value in margin_deltas.values()]
        margin_errors.extend(current_margin_errors)
        max_margin_error = max(current_margin_errors, default=0.0)
        same_margins = not margin_deltas or max_margin_error <= tolerance_pt
        geometry = {
            "index": index,
            "source_width_pt": source_page["width_pt"],
            "source_height_pt": source_page["height_pt"],
            "target_width_pt": target_page["width_pt"],
            "target_height_pt": target_page["height_pt"],
            "width_delta_pt": round(width_delta, 3),
            "height_delta_pt": round(height_delta, 3),
            "dimension_error_pt": round(dimension_error, 3),
            "max_dimension_error_pt": round(max_dimension_error, 3),
            "same_size": same_size,
            "margin_deltas": margin_deltas,
            "max_margin_error_pt": round(max_margin_error, 3),
            "same_margins": same_margins,
            "same_geometry": same_size and same_margins,
        }
        page_geometry.append(geometry)
        if not same_size:
            issues.append(
                ConversionIssue(
                    IssueSeverity.LOSS,
                    "page-geometry",
                    f"page {index + 1} size changed by {width_delta:.2f} x {height_delta:.2f} pt",
                    f"pages[{index}]",
                )
            )
        if not same_margins:
            issues.append(
                ConversionIssue(
                    IssueSeverity.LOSS,
                    "page-margins",
                    f"page {index + 1} margins changed by up to {max_margin_error:.2f} pt",
                    f"pages[{index}]",
                )
            )
    summary: dict[str, float | int] = {
        "source_pages": len(source_pages),
        "target_pages": len(target_pages),
        "compared_pages": min(len(source_pages), len(target_pages)),
        "missing_pages": missing_pages,
        "tolerance_pt": tolerance_pt,
        "max_dimension_error_pt": round(max(dimension_errors, default=0.0), 3),
        "mean_dimension_error_pt": round(_mean(dimension_errors), 3),
        "rms_dimension_error_pt": round(_rms(dimension_errors), 3),
        "max_margin_error_pt": round(max(margin_errors, default=0.0), 3),
        "mean_margin_error_pt": round(_mean(margin_errors), 3),
        "rms_margin_error_pt": round(_rms(margin_errors), 3),
    }
    return page_geometry, summary, issues


def _compare_resources(
    source_resources: list[dict[str, Any]],
    target_resources: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[ConversionIssue]]:
    source_hashes = Counter(item["sha256"] for item in source_resources if item.get("sha256"))
    target_hashes = Counter(item["sha256"] for item in target_resources if item.get("sha256"))
    matched_hashes = source_hashes & target_hashes
    exact_matches = sum(matched_hashes.values())
    remaining_targets = target_hashes.copy()
    lost_resources = []
    for item in source_resources:
        digest = item.get("sha256")
        if digest and remaining_targets[digest] > 0:
            remaining_targets[digest] -= 1
        else:
            lost_resources.append(_resource_identity(item))
    remaining_sources = source_hashes.copy()
    added_resources = []
    for item in target_resources:
        digest = item.get("sha256")
        if digest and remaining_sources[digest] > 0:
            remaining_sources[digest] -= 1
        else:
            added_resources.append(_resource_identity(item))
    source_by_id = {item.get("id"): item for item in source_resources if item.get("id")}
    target_by_id = {item.get("id"): item for item in target_resources if item.get("id")}
    changed_ids = [
        {
            "id": resource_id,
            "source_sha256": source_by_id[resource_id].get("sha256"),
            "target_sha256": target_by_id[resource_id].get("sha256"),
        }
        for resource_id in sorted(source_by_id.keys() & target_by_id.keys())
        if source_by_id[resource_id].get("sha256") != target_by_id[resource_id].get("sha256")
    ]
    source_bytes = sum(int(item.get("size_bytes") or 0) for item in source_resources)
    target_bytes = sum(int(item.get("size_bytes") or 0) for item in target_resources)
    matched_bytes = sum(
        int(next(item.get("size_bytes") or 0 for item in source_resources if item.get("sha256") == digest)) * count
        for digest, count in matched_hashes.items()
    )
    source_types = Counter(str(item.get("media_type") or "") for item in source_resources)
    target_types = Counter(str(item.get("media_type") or "") for item in target_resources)
    matched_types = sum((source_types & target_types).values())
    comparison = {
        "source_count": len(source_resources),
        "target_count": len(target_resources),
        "exact_hash_matches": exact_matches,
        "exact_hash_retention_ratio": round(_ratio(exact_matches, len(source_resources)), 4),
        "source_bytes": source_bytes,
        "target_bytes": target_bytes,
        "exact_bytes_retained": matched_bytes,
        "exact_byte_retention_ratio": round(_ratio(matched_bytes, source_bytes), 4),
        "media_type_retention_ratio": round(_ratio(matched_types, len(source_resources)), 4),
        "lost_resources": lost_resources,
        "added_resources": added_resources,
        "changed_ids": changed_ids,
    }
    issues = [
        ConversionIssue(
            IssueSeverity.LOSS,
            "resource-loss",
            f"{len(lost_resources)} resource(s) lost or changed; {exact_matches} of {len(source_resources)} hashes retained",
        )
    ] if lost_resources else []
    return comparison, issues


def _compare_fonts(
    source_fonts: dict[str, int],
    target_fonts: dict[str, int],
) -> tuple[dict[str, Any], list[ConversionIssue]]:
    source = _normalised_fonts(source_fonts)
    target = _normalised_fonts(target_fonts)
    preserved = source & target
    missing = source - target
    added = target - source
    source_runs = sum(source.values())
    preserved_runs = sum(preserved.values())
    candidates = _font_substitution_candidates(missing, added)
    comparison = {
        "source_families": dict(sorted(source.items())),
        "target_families": dict(sorted(target.items())),
        "preserved_families": sorted(preserved),
        "missing_families": dict(sorted(missing.items())),
        "added_families": dict(sorted(added.items())),
        "source_runs": source_runs,
        "target_runs": sum(target.values()),
        "preserved_runs": preserved_runs,
        "exact_run_retention_ratio": round(_ratio(preserved_runs, source_runs), 4),
        "possible_substitutions": candidates,
    }
    issues = []
    for family, count in sorted(missing.items()):
        replacements = [item["target"] for item in candidates if item["source"] == family]
        suffix = f"; possible replacement: {', '.join(replacements)}" if replacements else ""
        issues.append(
            ConversionIssue(
                IssueSeverity.LOSS,
                "font-substitution",
                f"font {family!r} missing for {count} run(s){suffix}",
            )
        )
    return comparison, issues


def _resource_identity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "kind": item.get("kind"),
        "media_type": item.get("media_type"),
        "size_bytes": int(item.get("size_bytes") or 0),
        "sha256": item.get("sha256"),
    }


def _normalised_fonts(fonts: dict[str, int]) -> Counter[str]:
    result: Counter[str] = Counter()
    for name, count in fonts.items():
        result[_normalise_font_name(name)] += count
    return result


def _normalise_font_name(name: str) -> str:
    family = re.sub(r"^[A-Z]{6}\+", "", name.strip())
    compact = re.sub(r"[\s_-]+", "", family).casefold()
    aliases = {
        "arial": "Arial",
        "arialmt": "Arial",
        "calibri": "Calibri",
        "calibrilight": "Calibri Light",
        "couriernew": "Courier New",
        "couriernewpsmt": "Courier New",
        "timesnewroman": "Times New Roman",
        "timesnewromanpsmt": "Times New Roman",
    }
    return aliases.get(compact, family.casefold())


def _font_substitution_candidates(missing: Counter[str], added: Counter[str]) -> list[dict[str, Any]]:
    available = added.copy()
    candidates: list[dict[str, Any]] = []
    for source_name, missing_count in missing.most_common():
        remaining = missing_count
        ranked_targets = sorted(available, key=lambda name: (abs(available[name] - missing_count), name))
        for target_name in ranked_targets:
            if remaining <= 0:
                break
            count = min(remaining, available[target_name])
            if count <= 0:
                continue
            candidates.append({"source": source_name, "target": target_name, "runs": count})
            available[target_name] -= count
            remaining -= count
    return candidates


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else min(numerator / denominator, 1.0)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values)) if values else 0.0


def inspect_document_model(
    document: DocumentModel,
    *,
    source_path: str | Path | None = None,
    source_format: str | None = None,
) -> DocumentInspection:
    """Собрать структурные метрики и диагностировать модель."""

    path = Path(source_path) if source_path is not None else None
    report = DocumentInspection(path, source_format or document.source_format or "document-model")
    report.metadata = dict(document.metadata)
    counters: Counter[str] = Counter(
        sections=len(document.sections),
        pages=len(document.sections),
        resources=len(document.resources),
        package_parts=len(document.package.parts) if document.package is not None else 0,
        package_relationships=len(document.package.relationships) if document.package is not None else 0,
        style_definitions=len(document.styles),
    )
    fonts: Counter[str] = Counter()
    formula_formats: Counter[str] = Counter()
    referenced_resources: set[str] = set()

    for error in document.validate():
        report.add(IssueSeverity.ERROR, "model-validation", error)
    for section_index, section in enumerate(document.sections):
        _inspect_page(section.page, section_index, report)
        for collection_name in (
            "headers",
            "first_page_headers",
            "even_page_headers",
            "blocks",
            "footers",
            "first_page_footers",
            "even_page_footers",
        ):
            blocks = getattr(section, collection_name)
            counters[f"{collection_name}_top_level"] += len(blocks)
            for block_index, block in enumerate(blocks):
                _inspect_block(
                    block,
                    f"sections[{section_index}].{collection_name}[{block_index}]",
                    section.page,
                    report,
                    counters,
                    fonts,
                    formula_formats,
                    referenced_resources,
                )
    for resource in document.resources.values():
        report.resources.append(_inspect_resource(resource, report))
    if document.package is not None:
        report.package_parts = [
            {
                "id": part.name,
                "media_type": part.media_type,
                "size_bytes": len(part.data),
                "sha256": hashlib.sha256(part.data).hexdigest(),
            }
            for part in document.package.parts.values()
        ]
    for resource_id in sorted(set(document.resources) - referenced_resources):
        report.add(IssueSeverity.WARNING, "unused-resource", f"resource {resource_id!r} is not referenced")

    report.metrics = dict(sorted(counters.items()))
    report.fonts = dict(fonts.most_common())
    report.formula_formats = dict(sorted(formula_formats.items()))
    return report


def inspect_path(path: str | Path) -> DocumentInspection:
    """Inspect DOCX, PDF, PPTX, HTML, LaTeX or a JSON-serialized DocumentModel."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    if suffix == ".docx":
        from textalchemy.formats.docx import read_docx_model

        return inspect_document_model(read_docx_model(source), source_path=source, source_format="docx")
    if suffix == ".json":
        from textalchemy.core.document_codec import load_document

        return inspect_document_model(load_document(source), source_path=source, source_format="document-model-json")
    if suffix == ".pdf":
        return _inspect_pdf(source)
    if suffix == ".pptx":
        from textalchemy.formats.pptx import read_pptx_model

        return inspect_document_model(read_pptx_model(source), source_path=source, source_format="pptx")
    if suffix == ".html":
        return _inspect_html(source)
    if suffix == ".tex":
        return _inspect_latex(source)
    raise TextAlchemyError(f"Unsupported inspection format: {suffix or '<none>'}")


def _inspect_page(page: PageSettings, section_index: int, report: DocumentInspection) -> None:
    location = f"sections[{section_index}].page"
    report.pages.append(
        {
            "index": section_index,
            "width_pt": page.width.pt,
            "height_pt": page.height.pt,
            "margin_top_pt": page.margin_top.pt,
            "margin_right_pt": page.margin_right.pt,
            "margin_bottom_pt": page.margin_bottom.pt,
            "margin_left_pt": page.margin_left.pt,
        }
    )
    if page.width.pt <= 0 or page.height.pt <= 0:
        report.add(IssueSeverity.ERROR, "page-geometry", "page dimensions must be positive", location)
    if min(page.margin_top.pt, page.margin_right.pt, page.margin_bottom.pt, page.margin_left.pt) < 0:
        report.add(IssueSeverity.ERROR, "page-geometry", "page margins must not be negative", location)
    if page.margin_left.pt + page.margin_right.pt >= page.width.pt:
        report.add(IssueSeverity.ERROR, "page-geometry", "horizontal margins consume the page width", location)
    if page.margin_top.pt + page.margin_bottom.pt >= page.height.pt:
        report.add(IssueSeverity.ERROR, "page-geometry", "vertical margins consume the page height", location)


def _inspect_block(
    block: Block,
    location: str,
    page: PageSettings,
    report: DocumentInspection,
    counters: Counter[str],
    fonts: Counter[str],
    formula_formats: Counter[str],
    referenced_resources: set[str],
) -> None:
    counters["blocks"] += 1
    _inspect_box(getattr(block, "box", None), page, report, location)
    if isinstance(block, Paragraph):
        counters["paragraphs"] += 1
        counters["styled_paragraphs"] += int(bool(block.style_id))
        counters["numbered_paragraphs"] += int(block.properties.get("numbering_id") is not None)
        for inline_index, item in enumerate(block.content):
            item_location = f"{location}.content[{inline_index}]"
            if isinstance(item, TextRun):
                counters["text_runs"] += 1
                counters["characters"] += len(item.text)
                counters["hyperlinks"] += int(bool(item.link or item.properties.get("hyperlink_anchor")))
                counters["internal_hyperlinks"] += int(bool(item.properties.get("hyperlink_anchor")))
                counters["bookmark_starts"] += int(item.properties.get("bookmark_start") is not None)
                counters["bookmark_ends"] += int(item.properties.get("bookmark_end_id") is not None)
                if item.properties.get("footnote_reference_id") is not None:
                    counters["footnote_references"] += 1
                if item.properties.get("endnote_reference_id") is not None:
                    counters["endnote_references"] += 1
                if item.properties.get("field_instruction") is not None:
                    counters["fields"] += 1
                if item.properties.get("field_complex"):
                    counters["complex_fields"] += 1
                if item.properties.get("resource_id"):
                    referenced_resources.add(str(item.properties["resource_id"]))
                if item.style.font_family:
                    fonts[item.style.font_family] += 1
            elif isinstance(item, Formula):
                _inspect_formula(item, item_location, page, report, counters, formula_formats)
            elif isinstance(item, Image):
                _inspect_image(item, item_location, page, report, counters, referenced_resources)
    elif isinstance(block, Table):
        counters["tables"] += 1
        counters["table_rows"] += len(block.rows)
        for row_index, row in enumerate(block.rows):
            counters["table_cells"] += len(row.cells)
            for cell_index, cell in enumerate(row.cells):
                counters["merged_cells"] += int(cell.row_span > 1 or cell.column_span > 1)
                for block_index, nested in enumerate(cell.blocks):
                    _inspect_block(
                        nested,
                        f"{location}.rows[{row_index}].cells[{cell_index}].blocks[{block_index}]",
                        page,
                        report,
                        counters,
                        fonts,
                        formula_formats,
                        referenced_resources,
                    )
    elif isinstance(block, Formula):
        _inspect_formula(block, location, page, report, counters, formula_formats)
    elif isinstance(block, Image):
        _inspect_image(block, location, page, report, counters, referenced_resources)


def _inspect_formula(
    formula: Formula,
    location: str,
    page: PageSettings,
    report: DocumentInspection,
    counters: Counter[str],
    formula_formats: Counter[str],
) -> None:
    counters["formulas"] += 1
    formula_formats[formula.format.value] += 1
    _inspect_box(formula.box, page, report, location)
    if not formula.value:
        report.add(IssueSeverity.ERROR, "formula", "formula source is empty", location)
    if not formula.fallback_text:
        report.add(IssueSeverity.WARNING, "formula-fallback", "formula has no portable fallback text", location)


def _inspect_image(
    image: Image,
    location: str,
    page: PageSettings,
    report: DocumentInspection,
    counters: Counter[str],
    referenced_resources: set[str],
) -> None:
    counters["images"] += 1
    counters["cropped_images"] += int(image.crop is not None)
    counters["rotated_images"] += int(bool(image.box and image.box.rotation))
    counters["floating_images"] += int(image.properties.get("placement") == "anchor")
    counters["wrap_polygon_images"] += int(bool(image.properties.get("wrap_polygon")))
    referenced_resources.add(image.resource_id)
    _inspect_box(image.box, page, report, location)
    if image.crop is not None:
        values = (image.crop.left, image.crop.top, image.crop.right, image.crop.bottom)
        if not all(math.isfinite(value) for value in values):
            report.add(IssueSeverity.ERROR, "image-crop", "crop values must be finite", location)
        if image.crop.left + image.crop.right >= 1 or image.crop.top + image.crop.bottom >= 1:
            report.add(IssueSeverity.ERROR, "image-crop", "crop removes the entire image", location)
    if not image.alt_text:
        report.add(IssueSeverity.WARNING, "image-alt-text", "image has no alternative text", location)


def _inspect_box(box: Box | None, page: PageSettings, report: DocumentInspection, location: str) -> None:
    if box is None:
        return
    if box.width < 0 or box.height < 0:
        report.add(IssueSeverity.ERROR, "element-geometry", "element dimensions must not be negative", location)
    if box.x < 0 or box.y < 0:
        report.add(IssueSeverity.WARNING, "element-geometry", "element starts outside the page", location)
    if box.x + box.width > page.width.pt or box.y + box.height > page.height.pt:
        report.add(IssueSeverity.WARNING, "element-geometry", "element extends beyond the page", location)


def _inspect_resource(resource: Resource, report: DocumentInspection) -> dict[str, Any]:
    raw = resource.data
    source_exists = None
    if raw is None and resource.source is not None:
        source = Path(resource.source)
        source_exists = source.is_file()
        size = source.stat().st_size if source_exists else 0
        digest = None
        if not source_exists:
            report.add(IssueSeverity.ERROR, "resource", f"resource source does not exist: {source}", resource.id)
    else:
        size = len(raw or b"")
        digest = hashlib.sha256(raw).hexdigest() if raw is not None else None
    return {
        "id": resource.id,
        "kind": resource.kind.value,
        "media_type": resource.media_type,
        "filename": resource.filename,
        "size_bytes": size,
        "sha256": digest,
        "embedded": raw is not None,
        "source_exists": source_exists,
    }


def _inspect_pdf(path: Path) -> DocumentInspection:
    import fitz
    from pypdf import PdfReader

    report = DocumentInspection(path, "pdf")
    counters: Counter[str] = Counter()
    fonts: Counter[str] = Counter()
    resources: dict[int, dict[str, Any]] = {}
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            password_status = reader.decrypt("")
        except Exception:  # noqa: BLE001 - damaged encryption dictionaries vary by producer
            password_status = 0
        if not password_status:
            report.add(IssueSeverity.ERROR, "encryption", "PDF requires a password for structural inspection")
            report.metrics = {"encrypted": 1}
            return report
        report.add(IssueSeverity.WARNING, "encryption", "PDF is encrypted with an empty password")
    counters["form_fields"] = len(reader.get_fields() or {})
    counters["pages"] = len(reader.pages)

    with fitz.open(path) as document:
        report.metadata = {key: value for key, value in document.metadata.items() if value}
        for page_index, page in enumerate(document):
            rectangle = page.rect
            report.pages.append(
                {
                    "index": page_index,
                    "width_pt": rectangle.width,
                    "height_pt": rectangle.height,
                    "rotation": page.rotation,
                }
            )
            page_dict = page.get_text("dict")
            text_blocks = [block for block in page_dict.get("blocks", []) if block.get("type") == 0]
            counters["text_blocks"] += len(text_blocks)
            page_characters = 0
            for block in text_blocks:
                for line in block.get("lines", []):
                    counters["text_lines"] += 1
                    for span in line.get("spans", []):
                        counters["text_runs"] += 1
                        page_characters += len(span.get("text", ""))
                        if span.get("font"):
                            fonts[str(span["font"])] += 1
            counters["characters"] += page_characters
            counters["hyperlinks"] += len(page.get_links())
            drawings = page.get_drawings()
            counters["vector_drawings"] += len(drawings)
            images = page.get_images(full=True)
            counters["image_occurrences"] += len(images)
            for item in images:
                xref = int(item[0])
                if xref not in resources:
                    extracted = document.extract_image(xref)
                    data = extracted.get("image", b"")
                    resources[xref] = {
                        "id": f"xref-{xref}",
                        "kind": "raster_image",
                        "media_type": f"image/{extracted.get('ext', 'unknown')}",
                        "filename": None,
                        "size_bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest() if data else None,
                        "embedded": True,
                        "width_px": extracted.get("width"),
                        "height_px": extracted.get("height"),
                    }
            counters["form_widgets"] += len(list(page.widgets() or []))
            if page_characters == 0 and not images and not drawings:
                report.add(
                    IssueSeverity.WARNING,
                    "blank-page",
                    "page has no text, images, or vector drawings",
                    f"pages[{page_index}]",
                )
    counters["resources"] = len(resources)
    report.metrics = dict(sorted(counters.items()))
    report.resources = list(resources.values())
    report.fonts = dict(fonts.most_common())
    return report


_HTML_SKIP_TAGS = {"script", "style", "head"}
_LATEX_MATH_ENVS = (
    "equation",
    "equation*",
    "align",
    "align*",
    "gather",
    "gather*",
    "alignat",
    "alignat*",
    "eqnarray",
    "eqnarray*",
    "multline",
    "multline*",
    "flalign",
    "flalign*",
)
_LATEX_PAPER_SIZES = {
    "a3paper": (841.89, 1190.55),
    "a4paper": (595.28, 841.89),
    "a5paper": (419.53, 595.28),
    "letterpaper": (612.0, 792.0),
    "legalpaper": (612.0, 1008.0),
}
_LATEX_TEXT_COMMANDS = re.compile(r"\\(?:textbf|textit|emph|text|mbox|mathrm|mathsf|mathtt|mathcal|underline|url)\{([^{}]*)\}")
_LATEX_REF_COMMANDS = re.compile(r"\\(?:eqref|pageref|cref|vref|label|ref)\{")
_LATEX_CITE_COMMANDS = re.compile(r"\\[a-zA-Z@]*cite[a-zA-Z@]*\{")
_LATEX_HREF_COMMANDS = re.compile(r"\\href\{")
_LATEX_DISPLAY_MATH = re.compile(r"\$\$.*?\$\$|\\\[.*?\\\]", re.DOTALL)
_LATEX_INLINE_MATH = re.compile(r"(?<!\\)\$(?!\$)[^$\n]+(?<!\\)\$")
_LATEX_HEADING_COMMANDS = re.compile(r"\\(?:chapter|(?:sub)*section)\*?\{")
_LATEX_COMMAND_TOKEN = re.compile(r"\\[a-zA-Z@]+\*?")
_LATEX_BEGIN_END = re.compile(r"\\(?:begin|end)\{[a-zA-Z*]+\}")
_LATEX_ESCAPES = {
    r"\%": "%",
    r"\&": "&",
    r"\_": "_",
    r"\#": "#",
    r"\$": "$",
    r"\{": "{",
    r"\}": "}",
    r"\textbackslash": "\\",
    r"\textasciitilde": "~",
    r"\textasciicircum": "^",
    r"\ldots": "…",
    r"\textendash": "–",
    r"\textemdash": "—",
    r"\textquotedbl": '"',
    r"\textquoteleft": "‘",
    r"\textquoteright": "’",
    r"\textbullet": "•",
}


class _HtmlInspectionParser(HTMLParser):
    """Собрать структурные метрики и data-URI ресурсы из HTML."""

    def __init__(self, report: DocumentInspection) -> None:
        super().__init__(convert_charrefs=True)
        self.report = report
        self.counters: Counter[str] = Counter()
        self.fonts: Counter[str] = Counter()
        self.resources: dict[str, dict[str, Any]] = {}
        self._skip_depth = 0
        self._math_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if tag in _HTML_SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "section":
            self.counters["sections"] += 1
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.counters["headings"] += 1
        elif tag == "p":
            self.counters["paragraphs"] += 1
        elif tag == "table":
            self.counters["tables"] += 1
        elif tag == "tr":
            self.counters["table_rows"] += 1
        elif tag in {"td", "th"}:
            self.counters["table_cells"] += 1
        elif tag == "img":
            self.counters["images"] += 1
            self._inspect_image(attributes.get("src", ""))
        elif tag == "a":
            href = attributes.get("href")
            if href:
                if href.startswith("#"):
                    self.counters["internal_hyperlinks"] += 1
                else:
                    self.counters["hyperlinks"] += 1
        elif tag == "math":
            self.counters["formulas"] += 1
            self._math_depth += 1
        elif tag in {"ul", "ol"}:
            self.counters["lists"] += 1
        elif tag == "li":
            self.counters["list_items"] += 1
        style = attributes.get("style")
        if style:
            self._extract_fonts(style)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in _HTML_SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "math":
            self._math_depth = max(0, self._math_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._math_depth or not data.strip():
            return
        self.counters["characters"] += len(data)
        self.counters["text_runs"] += 1

    def _inspect_image(self, source: str) -> None:
        match = re.match(r"data:(image/[a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=]+)", source)
        if not match:
            return
        media_type, encoded = match.groups()
        try:
            raw = base64.b64decode(encoded)
        except ValueError:
            return
        index = len(self.resources)
        self.resources[f"img-{index}"] = {
            "id": f"img-{index}",
            "kind": "raster_image",
            "media_type": media_type,
            "filename": None,
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "embedded": True,
        }

    def _extract_fonts(self, style: str) -> None:
        for match in re.finditer(r"font-family\s*:\s*([^;}]+)", style):
            family = match.group(1).strip().strip("'\"").split(",")[0].strip()
            if family:
                self.fonts[family] += 1


def _inspect_html(path: Path) -> DocumentInspection:
    """Собрать структурные метрики, ресурсы и шрифты из HTML-файла."""

    report = DocumentInspection(path, "html")
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="utf-8", errors="replace")
    parser = _HtmlInspectionParser(report)
    parser.feed(raw)
    report.metrics = dict(sorted(parser.counters.items()))
    report.resources = list(parser.resources.values())
    report.fonts = dict(parser.fonts.most_common())
    if parser.counters["formulas"]:
        report.formula_formats = {"mathml": parser.counters["formulas"]}
    return report


def _inspect_latex(path: Path) -> DocumentInspection:
    """Собрать структурные метрики и геометрию страницы из LaTeX-файла."""

    report = DocumentInspection(path, "latex")
    raw = path.read_text(encoding="utf-8", errors="replace")
    counters: Counter[str] = Counter()
    counters["pages"] = 1
    counters["characters"] = len(_strip_latex_text(raw))
    counters["text_runs"] = len(re.findall(r"\S+", _strip_latex_text(raw)))
    counters["headings"] = len(_LATEX_HEADING_COMMANDS.findall(raw))
    counters["tables"] = len(re.findall(r"\\begin\{tabular", raw))
    counters["images"] = len(re.findall(r"\\includegraphics\*?", raw))
    counters["hyperlinks"] = len(_LATEX_HREF_COMMANDS.findall(raw))
    counters["internal_hyperlinks"] = len(_LATEX_REF_COMMANDS.findall(raw))
    counters["citations"] = len(_LATEX_CITE_COMMANDS.findall(raw))
    counters["formulas"] = _count_latex_formulas(raw)
    counters["list_items"] = len(re.findall(r"\\item", raw))
    counters["paragraphs"] = _count_latex_paragraphs(raw)
    papersize = _latex_paper_size(raw)
    report.metrics = dict(sorted(counters.items()))
    if papersize is not None:
        report.pages = [
            {
                "index": 0,
                "width_pt": papersize[0],
                "height_pt": papersize[1],
            }
        ]
    if counters["formulas"]:
        report.formula_formats = {"latex": counters["formulas"]}
    return report


def _latex_paper_size(raw: str) -> tuple[float, float] | None:
    match = re.search(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}", raw)
    options = match.group(0) if match else ""
    for name, size in _LATEX_PAPER_SIZES.items():
        if name in options:
            return size
    return None


def _count_latex_formulas(raw: str) -> int:
    return len(_LATEX_DISPLAY_MATH.findall(raw)) + len(_LATEX_INLINE_MATH.findall(raw)) + sum(
        raw.count(rf"\begin{{{env}}}") for env in _LATEX_MATH_ENVS
    )


def _count_latex_paragraphs(raw: str) -> int:
    body = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", raw, re.DOTALL)
    source = body.group(1) if body else raw
    return sum(1 for block in re.split(r"\n\s*\n", source) if re.search(r"\w", _strip_latex_text(block)))


def _strip_latex_text(raw: str) -> str:
    text = re.sub(r"(?<!\\)%.*$", "", raw, flags=re.MULTILINE)
    text = _LATEX_DISPLAY_MATH.sub(" ", text)
    for env in _LATEX_MATH_ENVS:
        text = re.sub(rf"\\begin{{{env}}}.*?\\end{{{env}}}", " ", text, flags=re.DOTALL)
    text = _LATEX_INLINE_MATH.sub(" ", text)
    text = re.sub(r"\\href\{[^{}]*\}\{([^{}]*)\}", r"\1", text)
    text = _LATEX_CITE_COMMANDS.sub(" ", text)
    text = _LATEX_REF_COMMANDS.sub(" ", text)
    text = _LATEX_BEGIN_END.sub(" ", text)
    text = _LATEX_TEXT_COMMANDS.sub(r"\1", text)
    text = _LATEX_COMMAND_TOKEN.sub(" ", text)
    for token, replacement in _LATEX_ESCAPES.items():
        text = text.replace(token, replacement)
    text = text.replace("~", " ").replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", text).strip()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _quality_metrics(report: DocumentInspection) -> dict[str, int]:
    metrics = report.metrics
    return {
        "pages": metrics.get("pages", metrics.get("sections", 0)),
        "characters": metrics.get("characters", 0),
        "text_runs": metrics.get("text_runs", 0),
        "images": metrics.get("images", metrics.get("image_occurrences", 0)),
        "cropped_images": metrics.get("cropped_images", 0),
        "rotated_images": metrics.get("rotated_images", 0),
        "floating_images": metrics.get("floating_images", 0),
        "wrap_polygon_images": metrics.get("wrap_polygon_images", 0),
        "tables": metrics.get("tables", 0),
        "formulas": metrics.get("formulas", 0),
        "hyperlinks": metrics.get("hyperlinks", 0),
        "internal_hyperlinks": metrics.get("internal_hyperlinks", 0),
        "bookmark_starts": metrics.get("bookmark_starts", 0),
        "bookmark_ends": metrics.get("bookmark_ends", 0),
        "numbered_paragraphs": metrics.get("numbered_paragraphs", 0),
        "footnote_references": metrics.get("footnote_references", 0),
        "endnote_references": metrics.get("endnote_references", 0),
        "fields": metrics.get("fields", 0),
        "complex_fields": metrics.get("complex_fields", 0),
        "resources": metrics.get("resources", 0),
        "package_parts": metrics.get("package_parts", 0),
    }


__all__ = [
    "DocumentComparison",
    "DocumentInspection",
    "compare_inspections",
    "inspect_document_model",
    "inspect_path",
]
