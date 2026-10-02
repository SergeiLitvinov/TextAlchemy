"""Навигация в реально сериализованном HTML и публикация с бюджетом потерь."""

import pytest

from textalchemy.convert.html_verify import HtmlVerifyStage
from textalchemy.convert.html_writer import write_html_model
from textalchemy.convert.stages import StageContext
from textalchemy.core.document_model import DocumentModel, Paragraph, Section, TextRun
from textalchemy.formats.html import read_html_model


def test_table_target_survives_html_model_html(tmp_path):
    source = tmp_path / "source.html"
    source.write_text(
        '<p><a href="#таблица%26данные">Перейти</a></p><table id="таблица&amp;данные"><tr><td>42</td></tr></table>',
        encoding="utf-8",
    )
    model = read_html_model(source)
    output = tmp_path / "result.html"
    report = write_html_model(model, output)
    assert report.success
    assert 'id="таблица&amp;данные"' in output.read_text(encoding="utf-8")
    assert report.metrics["html_navigation"]["internal_links"] == 1
    assert report.metrics["html_navigation"]["verified"] is True
    reread = read_html_model(output)
    assert reread.sections[0].blocks[1].properties["anchor_id"] == "таблица&данные"


@pytest.mark.parametrize("duplicate", [False, True])
def test_export_reports_missing_or_ambiguous_target(tmp_path, duplicate):
    blocks = [Paragraph([TextRun("Go", link="#target")])]
    if duplicate:
        blocks.extend(Paragraph([TextRun("Target")], properties={"anchor_id": "target"}) for _ in range(2))
    output = tmp_path / "result.html"
    report = write_html_model(DocumentModel(sections=[Section(blocks=blocks)]), output)
    assert report.success and not report.lossless
    assert output.is_file()
    metric = report.metrics["html_navigation"]
    assert metric["missing_targets"] == int(not duplicate)
    assert metric["ambiguous_targets"] == int(duplicate)
    assert metric["verified"] is False
    assert any(issue.feature == "hyperlink" and issue.location.startswith("html:line[") for issue in report.issues)


def test_verify_checks_only_local_fragment_links(tmp_path):
    candidate = tmp_path / "candidate.html"
    candidate.write_text(
        '<a href="#">Top</a><a href="#TOP">Top fragment</a><a href="other.html#missing">Other</a>'
        '<a href="https://example.com/#missing">External</a><a href="#next">Forward</a>'
        '<p id="next">Target</p><svg><g id="unused"/><g id="unused"/></svg>',
        encoding="utf-8",
    )
    result = HtmlVerifyStage().execute(candidate, StageContext(tmp_path / "output.html"))
    assert result.value == candidate
    assert result.report.lossless
    assert result.report.metrics["html_navigation"]["internal_links"] == 2
    assert result.report.metrics["html_navigation"]["duplicate_ids"] == 1


@pytest.mark.parametrize("cancelled", [False, True])
def test_verify_read_failure_and_cancellation_are_errors(tmp_path, cancelled):
    result = HtmlVerifyStage().execute(
        tmp_path / "missing.html",
        StageContext(tmp_path / "output.html", cancelled=lambda: cancelled),
    )
    assert not result.report.success
    assert result.report.issues[0].feature == ("cancelled" if cancelled else "html-verify")


@pytest.mark.parametrize("existing", [False, True])
def test_failed_verification_preserves_output(tmp_path, monkeypatch, existing):
    from textalchemy.convert.stages import StageResult
    from textalchemy.core.diagnostics import ConversionReport, IssueSeverity

    def fail(self, value, context):
        report = ConversionReport(context.output_path)
        report.add(IssueSeverity.ERROR, "html-verify", "Cannot read candidate")
        return StageResult(value, report)

    monkeypatch.setattr(HtmlVerifyStage, "execute", fail)
    output = tmp_path / "result.html"
    if existing:
        output.write_bytes(b"previous")
    report = write_html_model(DocumentModel(), output)
    assert not report.success
    if existing:
        assert output.read_bytes() == b"previous"
    else:
        assert not output.exists()
    assert not list(tmp_path.glob(".textalchemy-html-*"))


@pytest.mark.parametrize("limit", [0, 1])
def test_executor_applies_loss_budget_to_verified_links(tmp_path, limit):
    from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
    from textalchemy.core.document_codec import save_document
    from textalchemy.core.quality_policy import QualityPolicy
    from textalchemy.core.types import DocFormat

    source, output = tmp_path / "model.json", tmp_path / "result.html"
    save_document(DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("Go", link="#missing")])])]), source)
    output.write_bytes(b"previous")
    report = ConversionExecutor().execute(
        ConversionRequest(source, output, DocFormat.MODEL, DocFormat.HTML, quality_policy=QualityPolicy(limit)),
    )
    assert report.success is (limit == 1)
    assert report.metrics["step_metrics"]["model.html"]["html_navigation"]["missing_targets"] == 1
    assert report.metrics["quality_gate"]["loss_issues"] == 1
    if limit == 0:
        assert output.read_bytes() == b"previous"
    else:
        assert 'href="#missing"' in output.read_text(encoding="utf-8")
