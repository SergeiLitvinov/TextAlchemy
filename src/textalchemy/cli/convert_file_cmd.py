"""Universal single-file conversion command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def cmd_convert_file(args: argparse.Namespace) -> int:
    from textalchemy.convert.executor import ConversionExecutor, ConversionRequest, infer_format
    from textalchemy.core.conversion_graph import DocumentFeature
    from textalchemy.core.document_model import ConversionMode
    from textalchemy.core.object_quality_policy import ObjectLossPolicy
    from textalchemy.core.quality_policy import QualityPolicy
    from textalchemy.core.text_quality_policy import resolve_text_policy
    from textalchemy.core.types import DocFormat

    input_path = Path(args.input)
    output_path = Path(args.output)
    try:
        source = DocFormat(args.source_format) if args.source_format else infer_format(input_path)
        target = DocFormat(args.target_format) if args.target_format else infer_format(output_path)
        limit = getattr(args, "max_loss_issues", None)
        policy = QualityPolicy(limit) if limit is not None else None
        object_limit = getattr(args, "max_lost_objects", None)
        object_policy = ObjectLossPolicy(object_limit) if object_limit is not None else None
        text_policy = resolve_text_policy(
            getattr(args, "require_unchanged_text", False), getattr(args, "text_preservation", None),
            getattr(args, "max_text_edits", None),
        )
    except ValueError as error:
        if args.json:
            print(json.dumps({"success": False, "error": str(error)}, ensure_ascii=False))
        else:
            print(f"Error: {error}")
        return 1
    features = (
        frozenset(DocumentFeature(value) for value in args.feature)
        if args.feature
        else frozenset(DocumentFeature)
    )
    report = ConversionExecutor().execute(
        ConversionRequest(
            input_path=input_path,
            output_path=output_path,
            source=source,
            target=target,
            mode=ConversionMode(args.mode),
            features=features,
            max_steps=args.max_steps,
            quality_policy=policy,
            object_loss_policy=object_policy,
            text_preservation_policy=text_policy,
        )
    )
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    elif report.success:
        print(f"Converted: {report.output_path}")
        print("Quality: " + ("lossless" if report.lossless else "with reported simplifications"))
        for step in report.metrics.get("executed_steps", []):
            print(f"  {step}")
    else:
        for issue in report.issues:
            print(f"Error: {issue.message}")
    return 0 if report.success else 1


__all__ = ["cmd_convert_file"]
