"""CLI-команда структурной инспекции документов."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def cmd_inspect(args: argparse.Namespace) -> int:
    from textalchemy.core.inspection import compare_inspections, inspect_path

    try:
        report = inspect_path(args.input)
        comparison = compare_inspections(report, inspect_path(args.compare)) if args.compare else None
        payload = (
            {
                "source": report.to_dict(),
                "target": comparison.target.to_dict(),
                "comparison": comparison.to_dict(),
            }
            if comparison is not None
            else report.to_dict()
        )
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if comparison is None:
                _print_inspection(report)
            else:
                print(f"Compare: {report.source_format} -> {comparison.target.source_format}")
                print(f"Valid: {'yes' if comparison.valid else 'no'}")
                for name, values in comparison.retention.items():
                    print(
                        f"  {name}: {values['source']} -> {values['target']} "
                        f"({float(values['ratio']) * 100:.1f}%)"
                    )
                geometry = comparison.geometry_summary
                print(
                    "Geometry: "
                    f"max page error {geometry['max_dimension_error_pt']:.3f} pt; "
                    f"max margin error {geometry['max_margin_error_pt']:.3f} pt"
                )
                resources = comparison.resource_comparison
                print(
                    "Resources: "
                    f"{resources['exact_hash_matches']}/{resources['source_count']} exact hashes "
                    f"({float(resources['exact_hash_retention_ratio']) * 100:.1f}%)"
                )
                fonts = comparison.font_comparison
                print(
                    "Fonts: "
                    f"{fonts['preserved_runs']}/{fonts['source_runs']} exact runs "
                    f"({float(fonts['exact_run_retention_ratio']) * 100:.1f}%)"
                )
                for issue in comparison.issues:
                    location = f" ({issue.location})" if issue.location else ""
                    print(f"  {issue.severity.value}: {issue.message}{location}")
        if not report.valid:
            return 1
        if comparison is not None and not comparison.valid:
            return 1
        if args.strict and (
            report.has_warnings
            or (comparison is not None and (comparison.target.has_warnings or comparison.has_losses))
        ):
            return 1
        return 0
    except Exception as error:  # noqa: BLE001 - machine-readable CLI boundary
        if args.json:
            print(json.dumps({"valid": False, "error": str(error)}, ensure_ascii=False))
        else:
            print(f"Error: {error}")
        return 1


def _print_inspection(report: Any) -> None:
    print(f"Format: {report.source_format}")
    print(f"Valid: {'yes' if report.valid else 'no'}")
    for name, value in report.metrics.items():
        print(f"  {name}: {value}")
    if report.fonts:
        print("Fonts: " + ", ".join(f"{name} ({count})" for name, count in report.fonts.items()))
    if report.issues:
        print("Issues:")
        for issue in report.issues:
            location = f" ({issue.location})" if issue.location else ""
            print(f"  {issue.severity.value}: {issue.message}{location}")


__all__ = ["cmd_inspect"]
