"""Finite PDF interactions: JSON preservation, explicit export loss and Web explanation."""

import pymupdf
import pytest
from opendoc_model import get_integration
from playwright.sync_api import expect

from tests import test_browser_e2e as browser_fixtures
from tests import test_web_m4_completion as api_fixtures
from tests.corpus.pdf_interactions import write_interactive_pdf
from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.document_codec import document_from_json, document_to_json
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.types import DocFormat
from textalchemy.web.queue import task_queue

m4_client = api_fixtures.m4_client
browser, page, e2e_server, task_store = (
    browser_fixtures.browser, browser_fixtures.page, browser_fixtures.e2e_server, browser_fixtures.task_store,
)


def converted(client, content, name, target, **policy):
    response = client.post("/api/convert", files={"file": (name, content)}, data={"target_format": target, **policy})
    assert response.status_code == 200, response.text
    assert task_queue.wait_idle(timeout=30)
    task = response.json()
    return client.get(task["status"]).json()["report"], client.get(task["result"])


@pytest.mark.parametrize("rotated", [False, True])
def test_pdf_interactions_survive_two_json_cycles_with_provenance(m4_client, tmp_path, rotated):
    client, _ = m4_client
    source = write_interactive_pdf(tmp_path / "interactive.pdf", rotated=rotated)
    original = source.read_bytes()
    report, output = converted(client, original, source.name, "model")
    assert report["success"] and output.status_code == 200
    for _ in range(2):
        model = document_from_json(output.text)
        integration = get_integration(model)
        assert integration.assessment_complete is False
        assert {a.kind for a in integration.annotations} == {"note", "highlight", "link"}
        assert next(a for a in integration.annotations if a.kind == "note").text == "Own note"
        assert next(a for a in integration.annotations if a.kind == "link").target == "https://example.invalid/"
        assert len(integration.forms) == 1 and integration.forms[0].value == "Initial"
        assert integration.forms[0].action["script"] == "/* Own inert QA marker */"
        assert integration.forms[0].box.x == 20 and integration.forms[0].box.y == 110
        assert integration.pages[0].extra["pdf_rotation"] == (90 if rotated else 0)
        assert integration.pages[0].extra["coordinate_space"] == "pymupdf-unrotated"
        assert model.resources["pdf-original-source"].data == original
        assert all(record.provenance.page == 1 and record.provenance.object_id.startswith("xref-")
                   for record in integration.preservation)
        report, output = converted(client, output.content, "interactive.json", "model")
        assert report["success"] and output.status_code == 200
    assert source.read_bytes() == original


def test_pdf_export_loss_budget_and_two_native_cycles(m4_client, tmp_path):
    client, _ = m4_client
    source = write_interactive_pdf(tmp_path / "interactive.pdf")
    original = source.read_bytes()
    report, model = converted(client, original, source.name, "model")
    assert report["success"]
    strict, result = converted(client, model.content, "interactive.json", "pdf", max_loss_issues="0")
    assert not strict["success"] and result.status_code == 409
    assert {i["feature"] for i in strict["issues"]} >= {"pdf.annotations", "pdf.forms", "quality-budget"}
    assert strict["metrics"]["quality_gate"]["loss_issues"] >= 2
    allowed, native = converted(client, model.content, "interactive.json", "pdf")
    assert allowed["success"] and not allowed["lossless"] and native.status_code == 200
    for _ in range(2):
        with pymupdf.open(stream=native.content, filetype="pdf") as pdf:
            assert "Own PDF acceptance" in " ".join(pdf[0].get_text().split())
            assert pdf[0].get_links() == [] and list(pdf[0].annots() or []) == [] and list(pdf[0].widgets() or []) == []
        _, plain_model = converted(client, native.content, "simplified.pdf", "model")
        assert plain_model.status_code == 200
        integration = get_integration(document_from_json(plain_model.text))
        assert not integration.annotations and not integration.forms
        _, native = converted(client, plain_model.content, "simplified.json", "pdf")
        assert native.status_code == 200
    assert source.read_bytes() == original


def test_opaque_annotation_outline_and_atomic_export_rejection(tmp_path):
    source = write_interactive_pdf(tmp_path / "opaque.pdf", unsupported=True)
    original = source.read_bytes()
    model, output = tmp_path / "opaque.json", tmp_path / "previous.pdf"
    executor = ConversionExecutor()
    imported = executor.execute(ConversionRequest(source, model, DocFormat.PDF, DocFormat.MODEL))
    assert imported.success and not imported.lossless
    assert imported.metrics["executed_steps"] == ["pdf.model"]
    diagnostics = imported.metrics["step_metrics"]["pdf.model"]["import_diagnostics"]
    assert {item["reason"] for item in diagnostics} >= {"unsupported-annotation", "outline-extension"}
    assert all(item["location"] for item in diagnostics)
    output.write_bytes(b"previous artifact")
    rejected = executor.execute(ConversionRequest(model, output, DocFormat.MODEL, DocFormat.PDF,
                                                 quality_policy=QualityPolicy(0)))
    assert not rejected.success and output.read_bytes() == b"previous artifact"
    assert source.read_bytes() == original


def test_small_pdf_known_text_clipping_is_not_called_preserved(m4_client, tmp_path):
    client, _ = m4_client
    source = write_interactive_pdf(tmp_path / "small.pdf", small=True)
    original = source.read_bytes()
    _, model = converted(client, original, source.name, "model")
    report, result = converted(client, model.content, "small.json", "pdf")
    assert report["success"] and result.status_code == 200
    with pymupdf.open(stream=original, filetype="pdf") as pdf:
        assert "Own PDF acceptance" in pdf[0].get_text()
        original_text = " ".join(pdf[0].get_text().split())
    with pymupdf.open(stream=result.content, filetype="pdf") as pdf:
        assert original_text != " ".join(pdf[0].get_text().split())
    strict, rejected = converted(client, model.content, "small.json", "pdf",
                                 text_preservation="flow", max_text_edits="0")
    assert not strict["success"] and rejected.status_code == 409
    assert strict["metrics"]["text_quality_gate"]["accepted"] is False
    assert source.read_bytes() == original


def test_cli_plan_declares_direct_pdf_import(capsys):
    import json

    from textalchemy.__main__ import main

    assert main(["plan", "pdf", "model", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [step["id"] for step in payload["steps"]] == ["pdf.model"]


@pytest.mark.parametrize("width", [375, 1280])
def test_browser_explains_lost_pdf_interactions(e2e_server, page, task_store, tmp_path, width):
    from opendoc_formats import read_document

    source = write_interactive_pdf(tmp_path / "interactive.pdf")
    model = tmp_path / "interactive.json"
    model.write_text(document_to_json(read_document(source).document), encoding="utf-8")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/convert")
    browser_fixtures._wait_convert_ready(page)
    page.locator("#fileInput").set_input_files(model)
    page.locator("#target").select_option("pdf")
    page.locator("#expertConversionBtn").click()
    page.locator(".conversion-loss-budget summary").click()
    page.locator("#maxLossIssues").select_option("0")
    page.locator("#convertBtn").click()
    expect(page.locator("#issueList")).to_contain_text("Поля PDF-формы", timeout=30000)
    expect(page.locator("#issueList")).to_contain_text("не создаются в итоговом PDF")
    expect(page.locator("#downloadBtn")).to_be_hidden()
    issue = page.locator("#issueList li").filter(has=page.get_by_text("Поля PDF-формы", exact=True))
    issue.locator("summary").click()
    expect(issue.locator(".issue-diagnostic p")).to_contain_text("Interactive objects are not recreated")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    from axe_core_python.sync_playwright import Axe

    assert not [i for i in Axe().run(page)["violations"] if i.get("impact") in {"serious", "critical"}]
    page.screenshot(path=str(tmp_path / f"pdf-interactions-{width}.png"), full_page=True)
    assert page.e2e_errors == []
