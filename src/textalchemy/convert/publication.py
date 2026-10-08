"""Atomic publication of conversions after independent quality checks."""

from __future__ import annotations

import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.types import DocFormat

if TYPE_CHECKING:
    from textalchemy.convert.executor import CancellationCheck, ConversionExecutor, ConversionRequest


def execute_with_quality(
    executor: ConversionExecutor,
    request: ConversionRequest,
    *,
    cancelled: CancellationCheck | None = None,
) -> ConversionReport:
    """Publish quality-gated output only after the whole route succeeds."""
    if request.target is not DocFormat.PDF and all(
        policy is None
        for policy in (
            request.quality_policy,
            request.object_loss_policy,
            request.text_preservation_policy,
            request.formula_loss_policy,
            request.emphasis_loss_policy,
            request.heading_loss_policy,
        )
    ):
        return executor._execute(request, cancelled=cancelled)
    report = ConversionReport(request.output_path)
    try:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".textalchemy-", dir=request.output_path.parent) as directory:
            staged = Path(directory) / request.output_path.name
            report = executor._execute(replace(request, output_path=staged), cancelled=cancelled)
            report.output_path = request.output_path
            if report.success and cancelled is not None and cancelled():
                return _cancelled_report(report)
            if report.success and any(
                policy is not None
                for policy in (
                    request.object_loss_policy,
                    request.text_preservation_policy,
                    request.formula_loss_policy,
                    request.emphasis_loss_policy,
                    request.heading_loss_policy, request.txt_encoding,
                )
            ):
                from textalchemy.convert.object_quality import check_object_quality

                check_object_quality(
                    request.input_path,
                    staged,
                    report,
                    request.object_loss_policy,
                    request.text_preservation_policy,
                    request.formula_loss_policy,
                    request.emphasis_loss_policy,
                    request.heading_loss_policy, request.txt_encoding,
                )
                if cancelled is not None and cancelled():
                    return _cancelled_report(report)
            if report.success and request.target is DocFormat.PDF:
                from textalchemy.convert.verification import verify_pdf_output

                verify_pdf_output(staged, report, cancelled=cancelled)
            if report.success and cancelled is not None and cancelled():
                return _cancelled_report(report)
            if report.success:
                if request.output_path.is_dir():
                    raise ValueError("Для публикации каталога выберите новый путь результата")
                os.replace(staged, request.output_path)
    except Exception as error:  # noqa: BLE001 - retain diagnostics on publication failure
        report.add(IssueSeverity.ERROR, "publication", str(error))
    return report


def _cancelled_report(report: ConversionReport) -> ConversionReport:
    report.metrics["cancelled"] = True
    report.add(IssueSeverity.ERROR, "cancelled", "conversion cancelled")
    return report
