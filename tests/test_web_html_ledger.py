"""Published HTML loss ledger remains enforceable after application JSON export."""

from tests import test_web_m4_completion as fixtures
from textalchemy.core.document_codec import document_from_json
from textalchemy.web.queue import task_queue

m4_client = fixtures.m4_client


def test_detected_html_loss_and_inert_source_survive_json(m4_client):
    client, _ = m4_client
    source = b'<style>p {display:grid}</style><script>alert(1)</script><p>Keep</p>'
    created = client.post("/api/convert", files={"file": ("limited.html", source)}, data={"target_format": "model"})
    assert created.status_code == 200, created.text
    assert task_queue.wait_idle(timeout=30)
    task = created.json()
    report = client.get(task["status"]).json()["report"]
    assert report["success"] and not report["lossless"]
    model = client.get(task["result"])
    assert model.status_code == 200
    document = document_from_json(model.text)
    attachment = document.resources["html-original-source"]
    assert attachment.kind.value == "attachment" and attachment.data == source
    assert document.sections[0].blocks[0].plain_text == "Keep"
    strict = client.post(
        "/api/convert", files={"file": ("limited.json", model.content)},
        data={"target_format": "html", "max_loss_issues": "0"},
    )
    assert strict.status_code == 200, strict.text
    assert task_queue.wait_idle(timeout=30)
    failed = strict.json()
    saved = client.get(failed["status"]).json()["report"]
    assert not saved["success"] and saved["metrics"]["quality_gate"]["loss_issues"] > 0
    assert client.get(failed["result"]).status_code == 409
