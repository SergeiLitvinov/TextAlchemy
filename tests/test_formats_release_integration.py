"""Consumer acceptance of published format diagnostics and explicit TXT profiles."""

import json

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from playwright.sync_api import expect

from tests import test_browser_e2e as browser_fixtures
from tests import test_web_m4_completion as api_fixtures
from textalchemy.__main__ import main
from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.text_quality_policy import resolve_text_policy
from textalchemy.core.types import DocFormat
from textalchemy.web.app import task_queue

m4_client = api_fixtures.m4_client

browser, page, e2e_server, task_store = (
    browser_fixtures.browser, browser_fixtures.page, browser_fixtures.e2e_server, browser_fixtures.task_store,
)


@pytest.mark.parametrize("encoding,bom", [("cp1251", b""), ("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")])
def test_explicit_profile_preserves_unicode_and_text_gate(tmp_path, encoding, bom):
    source, output = tmp_path / "source.txt", tmp_path / "result.json"
    text = "Иванов Иван Иванович\r\nЗапись №1"
    source.write_bytes(bom + text.encode(encoding))
    original = source.read_bytes()
    for _ in range(2):
        report = ConversionExecutor().execute(ConversionRequest(
            source, output, DocFormat.TXT, DocFormat.MODEL, txt_encoding=encoding,
            text_preservation_policy=resolve_text_policy(True, None)))
        assert report.success, report.to_dict()
        assert "Иванов Иван Иванович" in output.read_text(encoding="utf-8")
        assert report.metrics["text_quality_gate"]["accepted"]
    assert source.read_bytes() == original


def test_ambiguous_txt_preserves_previous_output_and_machine_reason(tmp_path):
    source, output = tmp_path / "source.txt", tmp_path / "result.html"
    source.write_bytes("Привет".encode("cp1251"))
    output.write_bytes(b"Previous output")
    report = ConversionExecutor().execute(ConversionRequest(source, output, DocFormat.TXT, DocFormat.HTML))
    assert not report.success and output.read_bytes() == b"Previous output"
    issue = report.metrics["step_metrics"]["txt.model"]["import_diagnostics"][0]
    assert issue["code"] == "import.txt-encoding" and issue["reason"] == "ambiguous-encoding"


def test_cli_explicit_cp1251(tmp_path, capsys):
    source, output = tmp_path / "source.txt", tmp_path / "result.json"
    source.write_bytes("Привет".encode("cp1251"))
    assert main(["convert-file", str(source), str(output), "--txt-encoding", "cp1251", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["success"]


def revision_fixture(path):
    document = Document()
    document.add_paragraph("Before")
    revision = OxmlElement("w:ins")
    revision.set(qn("w:id"), "8")
    paragraph, run, text = OxmlElement("w:p"), OxmlElement("w:r"), OxmlElement("w:t")
    text.text = "Tracked insertion"
    run.append(text)
    paragraph.append(run)
    revision.append(paragraph)
    document._element.body.insert(1, revision)
    document.save(path)


def test_docx_loss_reaches_budget_and_survives_json(tmp_path):
    source, model = tmp_path / "source.docx", tmp_path / "result.json"
    revision_fixture(source)
    original = source.read_bytes()
    executor = ConversionExecutor()
    report = executor.execute(ConversionRequest(source, model, DocFormat.DOCX, DocFormat.MODEL))
    assert report.success and not report.lossless
    diagnostics = report.metrics["step_metrics"]["docx.model"]["import_diagnostics"]
    issue = next(item for item in diagnostics if item["code"] == "docx.revisions")
    assert issue["severity"] == "loss" and issue["reason"] and issue["location"]
    assert issue["measurement"]["state"] == "lost"
    assert report.metrics["step_metrics"]["docx.model"]["assessment_complete"] is False
    for source_path, source_format in [(source, DocFormat.DOCX), (model, DocFormat.MODEL)]:
        output = tmp_path / "strict.txt"
        output.write_bytes(b"Previous output")
        strict = executor.execute(ConversionRequest(
            source_path, output, source_format, DocFormat.TXT, quality_policy=QualityPolicy(0)))
        assert not strict.success and strict.metrics["quality_gate"]["loss_issues"] >= 1
        assert output.read_bytes() == b"Previous output"
    assert source.read_bytes() == original


@pytest.mark.parametrize("width", [375, 1280])
def test_browser_cp1251_and_saved_retry(e2e_server, page, task_store, tmp_path, width):
    source = tmp_path / "cp1251.txt"
    source.write_bytes("Иванов Иван Иванович".encode("cp1251"))
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{e2e_server}/convert")
    page.wait_for_function("document.querySelector('#fileInput').accept.includes('.txt')")
    page.locator("#fileInput").set_input_files(source)
    page.locator("#expertConversionBtn").click()
    page.locator(".conversion-loss-budget summary").click()
    page.locator("#txtEncoding").select_option("cp1251")
    page.locator("#target").select_option("html")
    page.locator("#convertBtn").click()
    expect(page.locator("#downloadBtn")).to_be_visible(timeout=30000)
    tasks = task_store.list_tasks(limit=None)
    task = next(item for item in tasks if item.get("source_name") == "cp1251.txt")
    assert task["txt_encoding"] == "cp1251" and task["status"] == "done"
    import httpx

    with httpx.Client(base_url=e2e_server) as client:
        result = client.get(f"/api/convert/result/{task['task_id']}")
        assert "Иванов Иван Иванович" in result.text
        retry = client.post(f"/api/tasks/{task['task_id']}/rerun")
        assert retry.status_code == 200
        assert task_queue.wait_idle(timeout=30)
        assert task_store.get(task["task_id"])["txt_encoding"] == "cp1251"
        assert "Иванов Иван Иванович" in client.get(f"/api/convert/result/{task['task_id']}").text
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(tmp_path / f"txt-profile-{width}.png"), full_page=True)
    assert page.e2e_errors == []


@pytest.mark.parametrize("endpoint,field", [("/api/convert", "file"), ("/api/convert/batch", "files")])
def test_invalid_text_profile_creates_no_tasks(m4_client, endpoint, field):
    client, store = m4_client
    before = store.list_tasks(limit=None)
    response = client.post(endpoint, files={field: ("source.txt", b"Text")}, data={"txt_encoding": "utf-32"})
    assert response.status_code == 400
    assert store.list_tasks(limit=None) == before


def test_batch_text_profile_is_durable(m4_client):
    client, store = m4_client
    response = client.post("/api/convert/batch", files=[
        ("files", ("first.txt", "Первый".encode("cp1251"))),
        ("files", ("second.txt", "Второй".encode("cp1251"))),
    ], data={"target_format": "model", "txt_encoding": "cp1251"})
    assert response.status_code == 200, response.text
    created = response.json()
    for cycle in range(2):
        assert task_queue.wait_idle(timeout=30)
        for item, text in zip(created["tasks"], ["Первый", "Второй"], strict=True):
            task = store.get(item["task_id"])
            assert task["status"] == "done" and task["txt_encoding"] == "cp1251"
            assert text in client.get(item["result"]).text
        if cycle == 0:
            retry = client.post(f"/api/convert/jobs/{created['job_id']}/rerun", data={"failed_only": "false"})
            assert retry.status_code == 200, retry.text
