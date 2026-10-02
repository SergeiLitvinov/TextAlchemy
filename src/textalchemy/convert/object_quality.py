"""Inspect the serialized result before publishing an object-budgeted conversion."""

from pathlib import Path

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.emphasis_quality import EmphasisLossPolicy
from textalchemy.core.formula_quality_policy import FormulaLossPolicy
from textalchemy.core.inspection import compare_inspections, inspect_path
from textalchemy.core.object_quality_policy import ObjectLossPolicy
from textalchemy.core.text_quality_policy import TextPreservationPolicy


def check_object_quality(
    source: Path, target: Path, report: ConversionReport, policy: ObjectLossPolicy | None,
    text_policy: TextPreservationPolicy | None = None,
    formula_policy: FormulaLossPolicy | None = None, emphasis_policy: EmphasisLossPolicy | None = None,
) -> None:
    comparison = None
    try:
        comparison = compare_inspections(inspect_path(source), inspect_path(target))
    except Exception as error:  # noqa: BLE001 - inspection failure must fail the gate, not publish unchecked output
        report.add(IssueSeverity.WARNING, "object-inspection", f"Проверка объектов недоступна: {error}")
    if policy is not None:
        policy.evaluate(report, comparison)
    if text_policy is not None:
        text_policy.evaluate(report, comparison)
    if formula_policy is not None:
        formula_policy.evaluate(report, comparison)
    if emphasis_policy is not None:
        emphasis_policy.evaluate(report, comparison)
