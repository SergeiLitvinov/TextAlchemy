"""Проверка бюджета фактических диагностик на исполняемом маршруте."""

import pytest

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.conversion_graph import CapabilityRegistry, ConverterCapabilities, FeatureSupport
from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import ConversionMode, DocumentModel
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.types import DocFormat


@pytest.mark.parametrize("limit, expected", [(0, False), (1, True)])
def test_quality_budget_stops_route_before_export(tmp_path, limit, expected):
    registry = CapabilityRegistry()
    from textalchemy.core.conversion_graph import DocumentFeature

    for name, source, target in [("read", DocFormat.TXT, DocFormat.MODEL), ("write", DocFormat.MODEL, DocFormat.HTML)]:
        registry.register(ConverterCapabilities(
            name, source, target, frozenset({ConversionMode.BALANCED}), {DocumentFeature.TEXT: FeatureSupport.EXACT},
        ))
    calls = []

    def read(value, output):
        report = ConversionReport(output)
        report.add(IssueSeverity.LOSS, "table", "Table lost")
        return DocumentModel(), report

    def write(value, output):
        calls.append("write")
        output.write_text("result", encoding="utf-8")
        return output, None

    source, output = tmp_path / "in.txt", tmp_path / "out.html"
    source.write_text("source", encoding="utf-8")
    executor = ConversionExecutor(registry=registry, handlers={"read": read, "write": write})
    report = executor.execute(
        ConversionRequest(source, output, DocFormat.TXT, DocFormat.HTML, quality_policy=QualityPolicy(limit))
    )

    assert report.success is expected
    assert bool(calls) is expected
    assert output.exists() is expected
    assert report.metrics["quality_gate"]["loss_issues"] == 1
    assert report.metrics["quality_gate"]["visual_score"] is None


@pytest.mark.parametrize("limit", [-1, True, 1.5])
def test_invalid_quality_budget_is_rejected(limit):
    with pytest.raises(ValueError):
        QualityPolicy(limit)


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("outcome", ["loss", "error", "cancel", "success"])
def test_export_is_published_only_when_accepted(tmp_path, existing, outcome):
    from textalchemy.core.conversion_graph import DocumentFeature

    source, output = tmp_path / "in.txt", tmp_path / "out.html"
    source.write_text("source", encoding="utf-8")
    if existing:
        output.write_bytes(b"previous result")
    registry = CapabilityRegistry()
    registry.register(ConverterCapabilities(
        "write", DocFormat.TXT, DocFormat.HTML, frozenset({ConversionMode.BALANCED}),
        {DocumentFeature.TEXT: FeatureSupport.EXACT},
    ))
    stop = False

    def write(value, destination):
        nonlocal stop
        destination.write_bytes(b"new result")
        report = ConversionReport(destination)
        if outcome == "loss":
            report.add(IssueSeverity.LOSS, "table", "Table lost during export")
        if outcome == "error":
            raise RuntimeError("Exporter failed after writing")
        stop = outcome == "cancel"
        return destination, report

    report = ConversionExecutor(registry=registry, handlers={"write": write}).execute(
        ConversionRequest(source, output, DocFormat.TXT, DocFormat.HTML, quality_policy=QualityPolicy(0)),
        cancelled=lambda: stop,
    )
    assert report.output_path == output
    assert report.success is (outcome == "success")
    if outcome == "success":
        assert output.read_bytes() == b"new result"
    elif existing:
        assert output.read_bytes() == b"previous result"
    else:
        assert not output.exists()
    assert source.read_text(encoding="utf-8") == "source"
    assert not list(tmp_path.glob(".textalchemy-*"))


def test_txt_model_docx_roundtrip_preserves_blank_lines_and_edits(tmp_path):
    from textalchemy.core.document_codec import load_document, save_document
    from textalchemy.core.document_model import TextRun
    from textalchemy.formats.docx import read_docx_model

    source, model_path, output = tmp_path / "in.txt", tmp_path / "model.json", tmp_path / "out.docx"
    source.write_bytes("Первый\r\n\r\nПоследний\r\n".encode("cp1251"))
    executor = ConversionExecutor()
    first = executor.execute(ConversionRequest(source, model_path, DocFormat.TXT, DocFormat.MODEL))
    assert first.success
    model = load_document(model_path)
    assert [block.plain_text for block in model.sections[0].blocks] == ["Первый", "", "Последний", ""]
    model.sections[0].blocks[2].content = [TextRun("Изменённый")]
    save_document(model, model_path)
    second = executor.execute(ConversionRequest(model_path, output, DocFormat.MODEL, DocFormat.DOCX))
    assert second.success
    restored = read_docx_model(output)
    assert [block.plain_text for block in restored.sections[0].blocks] == ["Первый", "", "Изменённый", ""]
