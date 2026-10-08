"""Application publication limit over public heading-comparison measurements."""

from dataclasses import dataclass

from opendoc_model import ConversionReport, DocumentComparison, IssueSeverity
from opendoc_model.object_inventory import OBJECT_INVENTORY_SCOPE


@dataclass(frozen=True)
class HeadingBudget:
    """Choose a threshold; semantic inspection and matching remain library-owned."""

    max_changed_headings: int = 0

    def __post_init__(self) -> None:
        if type(self.max_changed_headings) is not int or self.max_changed_headings < 0:
            raise ValueError("max_changed_headings must be a non-negative integer")

    def evaluate(self, report: ConversionReport, comparison: DocumentComparison | None) -> bool:
        diff = comparison.object_diff if comparison is not None else {}
        matching = diff.get("matching") or {}
        count = diff.get("changed_headings")
        available = (
            comparison is not None and comparison.valid
            and comparison.source.metadata.get("object_inventory_scope") == OBJECT_INVENTORY_SCOPE
            and comparison.target.metadata.get("object_inventory_scope") == OBJECT_INVENTORY_SCOPE
            and diff.get("available") is True and diff.get("headings_available") is True
            and type(count) is int and count >= 0 and isinstance(diff.get("lost"), list)
        )
        certain = all(type(matching.get(key)) is int and matching[key] == 0 for key in ("heuristic", "ambiguous"))
        verified = available and certain
        lost = sum(item.get("type") == "paragraph" and item.get("heading") is not None
                   for item in diff["lost"]) if verified else None
        changed = count + lost if verified else None
        accepted = verified and changed <= self.max_changed_headings
        report.metrics["heading_quality_gate"] = {
            "basis": "public_heading_comparison_v1", "scope": OBJECT_INVENTORY_SCOPE,
            "max_changed_headings": self.max_changed_headings, "changed_headings": changed,
            "unmatched_source_headings": lost, "verified": verified, "accepted": accepted,
            "reason": ("accepted" if accepted else "budget-exceeded") if verified else
                      ("uncertain-matching" if available else "unavailable"),
            "visual_score": None,
        }
        if not accepted:
            message = (
                f"Изменены или удалены роли заголовков: {changed}; допустимо: {self.max_changed_headings}."
                if verified else "Бюджет заголовков не удалось проверить: данные неполные или сопоставление неоднозначно."
            )
            report.add(IssueSeverity.ERROR, "heading-quality-budget", message)
        return accepted
