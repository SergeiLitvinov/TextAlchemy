"""Storage contract doubles do not constitute real Word acceptance."""

import copy
import importlib
import json
from hashlib import sha256

import pytest

from textalchemy.web.services.target_program_evidence import validated_check
from textalchemy.web.tasks import TaskStore


@pytest.fixture
def stored_result(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    result = tmp_path / "result.docx"
    result.write_bytes(b"Storage contract fixture, not a Word document")
    name = store.store_artifact("sample", result, "result.docx")
    store.set("sample", {"status": "done", "target_format": "docx", "artifact": name, "report": {"metrics": {}}})
    record = {
        "schema": "target-program-check-v1", "driver": "word-com",
        "program": {"name": "Microsoft Word", "version": "contract-double", "build": "storage-test"},
        "artifact_sha256": sha256(result.read_bytes()).hexdigest(), "edited_sha256": sha256(b"edited").hexdigest(),
        "checked_at": "2026-10-08T10:00:00+03:00", "scope": ["paragraph_text", "table_cell", "save_reopen"],
        "checks": {"text_edit": True, "table_cell_edit": True, "save_reopen": True}, "visual_score": 0.99,
    }
    return store, store.get("sample"), record


def test_restart_keeps_checksum_matched_evidence_without_extending_ttl(stored_result):
    store, task, record = stored_result
    assert store.store_target_program_check("sample", expected=task, evidence=record)
    reopened = TaskStore(store.root)
    evidence = reopened.target_program_checks("sample", expected=task)
    assert evidence[0]["editability_verified"] is True and evidence[0]["visual_score"] is None
    assert reopened.get("sample") == task == store.get("sample")
    record["checks"]["text_edit"] = False
    assert evidence[0]["checks"]["text_edit"] is True


def test_checks_without_declared_scope_are_rejected(stored_result):
    _, _, record = stored_result
    record["checks"]["heading_outline"] = True
    with pytest.raises(ValueError, match="declared scope"):
        validated_check(record)


@pytest.mark.parametrize("change", ["bytes", "metadata", "expiry"])
def test_stale_or_different_result_never_gets_a_witness(stored_result, monkeypatch, change):
    store, task, record = stored_result
    assert store.store_target_program_check("sample", expected=task, evidence=record)
    if change == "bytes":
        store.result_path("sample", task["artifact"]).write_bytes(b"Other result")
    elif change == "metadata":
        store.set("sample", {**task, "revision": 2})
    else:
        module = importlib.import_module("textalchemy.web.tasks")
        monkeypatch.setattr(module.time, "time", lambda: task["_ts"] + store.ttl_seconds + 1)
    assert not store.store_target_program_check("sample", expected=task, evidence=record)
    assert store.target_program_checks("sample", expected=task) == []


def test_retry_clears_evidence(stored_result):
    store, task, record = stored_result
    assert store.store_target_program_check("sample", expected=task, evidence=record)
    assert store.prepare_retry("sample", expected=task, updates={"report": None})
    assert not (store.root / "sample/qa").exists()
    assert store.target_program_checks("sample", expected=store.get("sample")) == []


@pytest.mark.parametrize("outcome", [False, None])
def test_negative_and_unknown_checks_are_not_promoted(stored_result, outcome):
    store, task, record = stored_result
    record["checks"]["text_edit"] = outcome
    assert store.store_target_program_check("sample", expected=task, evidence=record)
    assert store.target_program_checks("sample", expected=task)[0]["editability_verified"] is outcome


def test_write_failure_does_not_claim_evidence(stored_result, monkeypatch):
    store, task, record = stored_result

    def fail(*args, **kwargs):
        raise OSError("Disk full")

    monkeypatch.setattr("textalchemy.web.tasks.atomic_write_text", fail)
    with pytest.raises(OSError):
        store.store_target_program_check("sample", expected=task, evidence=record)
    assert store.target_program_checks("sample", expected=task) == []
    assert store.get("sample") == task


def test_corrupt_or_colliding_revision_cannot_publish_a_witness(stored_result):
    store, task, record = stored_result
    assert store.store_target_program_check("sample", expected=task, evidence=record)
    path, revision = store._target_check_path("sample", task)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["revision"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert store.target_program_checks("sample", expected=task) == []
    assert store.store_target_program_check("sample", expected=task, evidence=record)
    assert json.loads(path.read_text(encoding="utf-8"))["revision"] == revision


@pytest.mark.parametrize("field,value", [("driver", "fake"), ("artifact_sha256", "bad"), ("checked_at", "2026-10-08")])
def test_invalid_evidence_refused(stored_result, field, value):
    _, _, record = stored_result
    record = copy.deepcopy(record)
    record[field] = value
    with pytest.raises(ValueError):
        validated_check(record)
