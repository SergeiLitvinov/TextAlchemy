"""CLI for planning document conversion routes."""

from __future__ import annotations

import argparse
import json


def cmd_plan(args: argparse.Namespace) -> int:
    from textalchemy.convert.capabilities import create_capability_registry
    from textalchemy.core.conversion_graph import DocumentFeature, FeatureSupport
    from textalchemy.core.document_model import ConversionMode
    from textalchemy.core.types import DocFormat

    features = [DocumentFeature(value) for value in args.feature] if args.feature else list(DocumentFeature)
    target = DocFormat(args.target)
    plan = create_capability_registry().plan(
        DocFormat(args.source),
        target,
        mode=ConversionMode(args.mode),
        features=features,
        max_steps=args.max_steps,
        available=lambda step: target is not DocFormat.MODEL or step.target is DocFormat.MODEL,
    )
    if plan is None:
        payload = {
            "success": False,
            "source": args.source,
            "target": args.target,
            "mode": args.mode,
            "error": "conversion route not found",
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"No conversion route: {args.source} -> {args.target} ({args.mode})")
        return 1

    payload = {"success": True, **plan.to_dict()}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"Route: {args.source} -> {args.target} ({args.mode}), score {plan.score:.3f}")
    for index, step in enumerate(plan.steps, 1):
        print(f"  {index}. {step.id}: {step.source.value} -> {step.target.value}")
    losses = {
        feature.value: support.value
        for feature, support in plan.feature_support.items()
        if support is not FeatureSupport.EXACT
    }
    if losses:
        print("Expected simplifications:")
        for feature, support in sorted(losses.items()):
            print(f"  {feature}: {support}")
    if plan.executable_requirements:
        print("Requirements: " + ", ".join(plan.executable_requirements))
    return 0


__all__ = ["cmd_plan"]
