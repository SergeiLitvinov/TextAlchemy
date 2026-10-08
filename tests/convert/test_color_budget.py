"""Приёмка цветовых диагностик готового адаптера и прикладного бюджета."""

from pathlib import Path

import pytest
from opendoc_model import ColorValue, DocumentModel, Paragraph, Section, TextRun, TextStyle, save_document

from textalchemy.__main__ import main
from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.types import DocFormat


def color_source(path: Path) -> Path:
    """Синтетический CMYK-текст: один ICC-профиль и multiply в двух фрагментах."""
    color = ColorValue.from_cmyk(0.1, 0.2, 0.3, 0.4, icc_profile="Print-profile", blend_mode="multiply")
    document = DocumentModel(
        sections=[
            Section(
                blocks=[
                    Paragraph(
                        content=[
                            TextRun("First color fragment. ", style=TextStyle(color=color)),
                            TextRun("Second color fragment.", style=TextStyle(color=color)),
                        ]
                    )
                ]
            )
        ]
    )
    return save_document(document, path)


@pytest.mark.parametrize("target,losses", [(DocFormat.HTML, 1), (DocFormat.DOCX, 2), (DocFormat.PDF, 2)])
@pytest.mark.parametrize("accepted", [False, True])
def test_color_budget_controls_real_export_and_preserves_previous_file(
    tmp_path: Path,
    target: DocFormat,
    losses: int,
    accepted: bool,
) -> None:
    source = color_source(tmp_path / "source.json")
    original = source.read_bytes()
    output = tmp_path / f"result.{target.value}"
    output.write_bytes(b"Previous result")
    limit = losses if accepted else losses - 1
    report = ConversionExecutor().execute(
        ConversionRequest(
            source,
            output,
            DocFormat.MODEL,
            target,
            quality_policy=QualityPolicy(limit),
        )
    )
    assert report.success is accepted, report.to_dict()
    color_issues = [issue for issue in report.issues if issue.feature.startswith("color-")]
    assert {issue.feature for issue in color_issues} == (
        {"color-icc"} if target is DocFormat.HTML else {"color-icc", "color-blend"}
    )
    assert len(color_issues) == losses
    assert all(issue.location == "sections[0].blocks[0].content[0].style.color" for issue in color_issues)
    assert report.metrics["quality_gate"]["loss_issues"] == losses
    assert report.metrics["quality_gate"]["visual_score"] is None
    assert source.read_bytes() == original
    assert (output.read_bytes() != b"Previous result") is accepted
    assert not list(tmp_path.glob(".textalchemy-*"))


def test_cli_strict_color_budget_preserves_previous_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    source = color_source(tmp_path / "source.json")
    output = tmp_path / "result.docx"
    output.write_bytes(b"Previous result")
    assert main(["convert-file", str(source), str(output), "--max-loss-issues", "0", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["metrics"]["quality_gate"]["loss_issues"] == 2
    assert output.read_bytes() == b"Previous result"
