"""Restore independently selected checks from durable task metadata."""

from textalchemy.core.emphasis_quality import EmphasisLossPolicy
from textalchemy.core.formula_quality_policy import FormulaLossPolicy
from textalchemy.core.object_quality_policy import ObjectLossPolicy
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.text_quality_policy import resolve_text_policy


def request_policy_fields(task: dict) -> dict:
    emphasis_limit = task.get("max_changed_emphasis")
    formula_limit = task.get("max_changed_formulas")
    limit, object_limit = task.get("max_loss_issues"), task.get("max_lost_objects")
    return {
        "emphasis_loss_policy": EmphasisLossPolicy(emphasis_limit) if emphasis_limit is not None else None,
        "formula_loss_policy": FormulaLossPolicy(formula_limit) if formula_limit is not None else None,
        "quality_policy": QualityPolicy(limit) if limit is not None else None,
        "object_loss_policy": ObjectLossPolicy(object_limit) if object_limit is not None else None,
        "text_preservation_policy": resolve_text_policy(
            task.get("require_unchanged_text") is True, task.get("text_preservation"),
            task.get("max_text_edits"),
        ),
    }


def stored_policy_fields(
    quality, objects, required: bool, mode: str | None,
    max_text_edits: int | None = None, max_changed_formulas: int | None = None, max_changed_emphasis: int | None = None,
) -> dict:
    text_policy = resolve_text_policy(required, mode, max_text_edits)
    if max_changed_emphasis is not None:
        EmphasisLossPolicy(max_changed_emphasis)
    if max_changed_formulas is not None:
        FormulaLossPolicy(max_changed_formulas)
    return {
        "max_loss_issues": quality.max_loss_issues if quality is not None else None,
        "max_lost_objects": objects.max_lost_objects if objects is not None else None,
        "require_unchanged_text": required,
        "text_preservation": text_policy.mode if text_policy is not None else None,
        "max_text_edits": max_text_edits,
        "max_changed_formulas": max_changed_formulas,
        "max_changed_emphasis": max_changed_emphasis,
    }
