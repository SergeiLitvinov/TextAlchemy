"""Real consumer routes for native PDF paths and a bounded PNG replacement."""

import io
import json
import math

import pymupdf
import pytest
from opendoc_formats import read_document
from opendoc_model import Box, DocumentModel, Image, Resource, ResourceKind, Section, VisualSurrogate, save_document
from PIL import Image as PillowImage
from playwright.sync_api import expect

from tests import test_browser_e2e as browser_fixtures
from tests import test_web_m4_completion as api_fixtures
from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.document_codec import load_document
from textalchemy.core.types import DocFormat
from textalchemy.web.queue import task_queue

m4_client = api_fixtures.m4_client
browser, page, e2e_server, task_store = (
    browser_fixtures.browser, browser_fixtures.page, browser_fixtures.e2e_server, browser_fixtures.task_store,
)


def vector_pdf(path):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=120, height=120)
        shape = page.new_shape()
        shape.draw_bezier((10, 20), (30, 5), (70, 90), (100, 40))
        shape.finish(color=(0.2, 0.3, 0.7), width=3, stroke_opacity=0.4, closePath=False)
        shape.commit()
        page.draw_line((10, 105), (100, 105), color=(1, 0, 0), width=2)
        pdf.save(path)
    return path


def test_advertised_pdf_html_route_executes_through_model(m4_client, tmp_path):
    client, _store = m4_client
    source = tmp_path / "text.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "Own PDF text for HTML")
        pdf.save(source)
    original = source.read_bytes()
    started = client.post("/api/convert", files={"file": ("text.pdf", original)},
                          data={"target_format": "html", "mode": "balanced"})
    assert started.status_code == 200, started.text
    assert task_queue.wait_idle(timeout=30)
    status = client.get(started.json()["status"]).json()
    assert status["status"] == "done", status
    assert status["report"]["metrics"]["executed_steps"] == ["pdf.model", "model.html"]
    result = client.get(started.json()["result"])
    assert result.status_code == 200
    assert "text/html" in result.headers["content-type"]
    assert "Own PDF text for HTML" in result.text
    assert source.read_bytes() == original


def unsupported_model(tmp_path, surrogate=True):
    source = vector_pdf(tmp_path / "paths.pdf")
    model = read_document(source).document
    resource = next(resource for resource in model.resources.values() if resource.media_type == "application/pdf+vector")
    resource.properties["items"] = [["unknown"]]
    if surrogate:
        buffer = io.BytesIO()
        PillowImage.new("RGB", (20, 20), "red").save(buffer, format="PNG")
        model.resources["visual"] = Resource("visual", ResourceKind.RASTER_IMAGE, "image/png", data=buffer.getvalue())
        image = model.sections[0].blocks[0].content[0]
        image.visual_surrogate = VisualSurrogate("visual", "unsupported command in own fixture", "image/png")
    return save_document(model, tmp_path / "unsupported.json")


def test_native_pdf_model_pdf_two_cycles_keep_vectors_and_pixels(m4_client, tmp_path):
    client, store = m4_client
    source = vector_pdf(tmp_path / "paths.pdf")
    original = source.read_bytes()
    content = original
    with pymupdf.open(source) as pdf:
        expected = pdf[0].get_pixmap().samples
    for cycle in range(2):
        imported = client.post("/api/convert", files={"file": ("paths.pdf", content)},
                               data={"target_format": "model"})
        assert imported.status_code == 200, imported.text
        assert task_queue.wait_idle(timeout=30)
        import_task = store.get(imported.json()["task_id"])
        assert import_task["status"] == "done", import_task
        assert import_task["report"]["metrics"]["executed_steps"] == ["pdf.model"]
        model_data = client.get(imported.json()["result"]).content
        exported = client.post("/api/convert", files={"file": ("paths.json", model_data)},
                               data={"target_format": "pdf", "max_loss_issues": 0})
        assert exported.status_code == 200
        assert task_queue.wait_idle(timeout=30)
        task = store.get(exported.json()["task_id"])
        assert task["status"] == "done", task
        vectors = task["report"]["metrics"]["step_metrics"]["model.pdf"]["pdf_vectors"]
        assert vectors["native"] == 2 and vectors["commands"] == 2
        content = client.get(exported.json()["result"]).content
        with pymupdf.open(stream=content, filetype="pdf") as result:
            assert len(result) == 1 and result[0].get_images() == []
            assert len(result[0].get_drawings()) == 2
            assert result[0].get_pixmap().samples == expected
        (tmp_path / f"cycle-{cycle+1}.pdf").write_bytes(content)
    assert source.read_bytes() == original


@pytest.mark.parametrize("limit", [0, 1, 2])
def test_surrogate_report_budget_and_retry(m4_client, tmp_path, limit):
    client, store = m4_client
    source = unsupported_model(tmp_path)
    original = source.read_bytes()
    created = client.post("/api/convert", files={"file": (source.name, original)},
                          data={"target_format": "pdf", "max_loss_issues": limit}).json()
    for cycle in range(2):
        assert task_queue.wait_idle(timeout=30)
        task = store.get(created["task_id"])
        assert task["status"] == ("done" if limit >= 2 else "error"), task
        issue = next(item for item in task["report"]["issues"] if item["feature"] == "pdf-vector-surrogate")
        assert issue["severity"] == "loss" and "unsupported vector command" in issue["message"]
        assert issue["location"] == "sections[0].blocks[0].content[0]"
        assert task["report"]["metrics"]["quality_gate"]["loss_issues"] == 2
        assert any(item["feature"] == "pdf-raster-compositing" and item["severity"] == "loss"
                   for item in task["report"]["issues"])
        if limit >= 2:
            data = client.get(created["result"]).content
            with pymupdf.open(stream=data, filetype="pdf") as pdf:
                assert len(pdf[0].get_images()) == 1
                paths = [path for path in pdf[0].get_drawings() if path.get("color") is not None]
                assert len(paths) == 1 and paths[0]["items"][0][0] == "l"
        else:
            assert client.get(created["result"]).status_code == 409
        if cycle == 0:
            assert client.post(f"/api/tasks/{created['task_id']}/rerun").status_code == 200
    assert source.read_bytes() == original


def test_missing_surrogate_rejects_and_keeps_previous_file(tmp_path):
    source = unsupported_model(tmp_path, surrogate=False)
    original = source.read_bytes()
    output = tmp_path / "previous.pdf"
    output.write_bytes(b"Previous result")
    report = ConversionExecutor().execute(ConversionRequest(source, output, DocFormat.MODEL, DocFormat.PDF))
    assert not report.success and output.read_bytes() == b"Previous result"
    assert any(issue.feature == "pdf-vector-unsupported" for issue in report.issues)
    assert source.read_bytes() == original
    assert load_document(source).resources


@pytest.mark.parametrize("width,limit", [(375, 0), (1280, 1), (1280, 5)])
def test_browser_explains_pdf_vector_surrogate(e2e_server, page, task_store, tmp_path, width, limit):
    source = unsupported_model(tmp_path)
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{e2e_server}/convert")
    browser_fixtures._wait_convert_ready(page)
    page.locator("#fileInput").set_input_files(source)
    page.locator("#target").select_option("pdf")
    page.locator("#expertConversionBtn").click()
    page.locator(".conversion-loss-budget summary").click()
    expect(page.locator("#txtInputProfile")).to_be_hidden()
    page.locator("#maxLossIssues").select_option(str(limit))
    page.locator("#convertBtn").click()
    expect(page.locator("#issueList")).to_contain_text("Замена PDF-вектора", timeout=30000)
    expect(page.locator("#issueList")).to_contain_text("Отдельные линии и кривые в нём не редактируются")
    expect(page.locator("#issueList")).to_contain_text("Наложение объектов PDF")
    expect(page.locator("#issueList")).to_contain_text("Порядок наложения")
    issue = page.locator("#issueList li").filter(has=page.get_by_text("Замена PDF-вектора", exact=True))
    expect(issue).to_contain_text("sections[0].blocks[0].content[0]")
    issue.locator("summary").click()
    expect(issue.locator(".issue-diagnostic p")).to_contain_text("unsupported vector command")
    if limit >= 2:
        expect(page.locator("#downloadBtn")).to_be_visible()
        expect(page.locator("#pdfVectorsSummary")).to_contain_text("Нативно записано PDF-векторов: 1")
    else:
        expect(page.locator("#downloadBtn")).to_be_hidden()
        expect(page.locator("#pdfVectorsSummary")).to_be_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    from axe_core_python.sync_playwright import Axe

    assert not [item for item in Axe().run(page)["violations"] if item.get("impact") in ("serious", "critical")]
    evidence = {"width": width, "limit": limit, "browser": page.context.browser.version,
                "tasks": task_store.list_tasks(limit=None), "office_editing_verified": None}
    (tmp_path / "vector-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    page.screenshot(path=str(tmp_path / f"vector-surrogate-{width}.png"), full_page=True)
    assert page.e2e_errors == []


@pytest.mark.parametrize("width", [375, 1280])
def test_browser_pdf_offers_public_model_route(e2e_server, page, task_store, tmp_path, width):
    source = vector_pdf(tmp_path / "paths.pdf")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{e2e_server}/convert")
    browser_fixtures._wait_convert_ready(page)
    page.locator("#fileInput").set_input_files(source)
    page.locator("#target").select_option("model")
    page.locator("#convertBtn").click()
    expect(page.locator("#downloadBtn")).to_be_visible(timeout=30000)
    task = next(item for item in task_store.list_tasks(limit=None) if item.get("source_name") == "paths.pdf")
    assert task["status"] == "done" and task["target_format"] == "model"
    assert task["report"]["metrics"]["executed_steps"] == ["pdf.model"]
    model = load_document(task_store.result_path(task["task_id"], task["artifact"]))
    assert len([resource for resource in model.resources.values() if resource.media_type == "application/pdf+vector"]) == 2
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.e2e_errors == []


def raster_model(path, *, invalid=False):
    buffer = io.BytesIO()
    PillowImage.new("RGB", (20, 20), "blue").save(buffer, format="PNG")
    model = DocumentModel(
        sections=[Section(blocks=[Image("own-raster", box=Box(20, 30, 40, 40, rotation=0 if invalid else 3))])],
        resources={"own-raster": Resource("own-raster", ResourceKind.RASTER_IMAGE, "image/png",
                                          data=buffer.getvalue()[:8] if invalid else buffer.getvalue())},
    )
    return save_document(model, path)


@pytest.mark.parametrize("width", [375, 1280])
def test_browser_explains_invalid_raster_refusal_without_offering_result(e2e_server, page, tmp_path, width):
    """A real damaged-PNG refusal remains a refusal, not accepted PDF quality."""
    source = raster_model(tmp_path / "invalid-raster.json", invalid=True)
    original = source.read_bytes()
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/convert")
    browser_fixtures._wait_convert_ready(page)
    page.locator("#fileInput").set_input_files(source)
    page.locator("#target").select_option("pdf")
    page.locator("#convertBtn").click()
    item = page.locator("#issueList li").filter(has=page.get_by_text("Изображение не перенесено в PDF", exact=True))
    expect(item).to_be_visible(timeout=30000)
    expect(item).to_contain_text("Экспорт остановлен, результат не выдан")
    expect(item).to_contain_text("sections[0].blocks[0]")
    item.locator("summary").click()
    expect(item.locator(".issue-diagnostic p")).to_contain_text("Invalid PNG header")
    expect(page.locator("#downloadBtn")).to_be_hidden()
    assert source.read_bytes() == original
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    from axe_core_python.sync_playwright import Axe

    assert not [v for v in Axe().run(page)["violations"] if v.get("impact") in ("critical", "serious")]
    assert page.e2e_errors == []


@pytest.mark.parametrize("width", [375, 1280])
def test_browser_exports_rotated_raster_in_two_cycles(e2e_server, page, task_store, tmp_path, width):
    """Two actual Web exports preserve a finite rotation and rendered pixels."""
    from axe_core_python.sync_playwright import Axe

    source = raster_model(tmp_path / "rotation-source.json")
    original = source.read_bytes()
    current = source
    first_pixels = None
    evidence = []
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(e2e_server + "/convert")
    browser_fixtures._wait_convert_ready(page)
    for cycle in (1, 2):
        page.locator("#fileInput").set_input_files(current)
        page.locator("#target").select_option("pdf")
        page.locator("#convertBtn").click()
        expect(page.locator("#downloadBtn")).to_be_visible(timeout=30000)
        task = next(item for item in task_store.list_tasks(limit=None) if item.get("source_name") == current.name)
        assert task["status"] == "done"
        result = task_store.result_path(task["task_id"], task["artifact"])
        with pymupdf.open(result) as pdf:
            assert len(pdf) == 1
            images = pdf[0].get_image_info()
            assert len(images) == 1
            transform = images[0]["transform"]
            angle = math.degrees(math.atan2(transform[1], transform[0]))
            assert angle == pytest.approx(3, abs=0.00001)
            center = (0.5 * (transform[0] + transform[2]) + transform[4],
                      0.5 * (transform[1] + transform[3]) + transform[5])
            assert center == pytest.approx((40, 50), abs=0.001)
            pixmap = pdf[0].get_pixmap(alpha=False)
            pixels = (pixmap.width, pixmap.height, pixmap.samples)
            if first_pixels is None:
                first_pixels = pixels
            else:
                assert pixels == first_pixels
            evidence.append({"cycle": cycle, "task_id": task["task_id"], "angle": angle,
                             "center": center, "page_size": [pixmap.width, pixmap.height]})
        imported_path = tmp_path / f"rotation-cycle-{cycle}.json"
        imported = ConversionExecutor().execute(ConversionRequest(result, imported_path, DocFormat.PDF, DocFormat.MODEL))
        assert imported.success, imported.to_dict()
        current = imported_path
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not [v for v in Axe().run(page)["violations"] if v.get("impact") in ("critical", "serious")]
    assert source.read_bytes() == original
    (tmp_path / "raster-rotation-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    assert page.e2e_errors == []
