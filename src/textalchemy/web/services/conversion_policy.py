"""Restore independently selected checks from durable task metadata."""

from textalchemy.core.object_quality_policy import ObjectLossPolicy
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.text_quality_policy import resolve_text_policy


def request_policy_fields(task: dict) -> dict:
    limit, object_limit = task.get("max_loss_issues"), task.get("max_lost_objects")
    return {
        "quality_policy": QualityPolicy(limit) if limit is not None else None,
        "object_loss_policy": ObjectLossPolicy(object_limit) if object_limit is not None else None,
        "text_preservation_policy": resolve_text_policy(
            task.get("require_unchanged_text") is True, task.get("text_preservation"),
            task.get("max_text_edits"),
        ),
    }


def stored_policy_fields(quality, objects, required: bool, mode: str | None, max_text_edits: int | None = None) -> dict:
    text_policy = resolve_text_policy(required, mode, max_text_edits)
    return {
        "max_loss_issues": quality.max_loss_issues if quality is not None else None,
        "max_lost_objects": objects.max_lost_objects if objects is not None else None,
        "require_unchanged_text": required,
        "text_preservation": text_policy.mode if text_policy is not None else None,
        "max_text_edits": max_text_edits,
    }
