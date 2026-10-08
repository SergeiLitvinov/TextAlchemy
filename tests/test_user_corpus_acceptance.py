"""Storage/observation invariants; doubles here are not native-program acceptance."""

import pytest

from tools.acceptance import corpus


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "ROOT", tmp_path / "application")
    root = tmp_path / "authorized"
    root.mkdir()
    original = root / "document.docx"
    original.write_bytes(b"storage-contract-fixture")
    manifest = {"source_root": str(root), "documents": [{"id": "case-01", "path": original.name}]}
    destination = corpus.ROOT / ".textalchemy/acceptance/run-01"
    return original, manifest, destination


def test_only_separate_copy_is_written_and_existing_run_is_preserved(source):
    original, manifest, destination = source
    before = original.read_bytes()
    selected = corpus.prepare(manifest, destination)
    assert selected[0]["copy"].read_bytes() == before
    assert selected[0]["source_sha256"] == corpus.digest(original)
    selected[0]["copy"].write_bytes(b"edited working copy")
    assert original.read_bytes() == before
    assert sorted(p.name for p in original.parent.iterdir()) == [original.name]
    with pytest.raises(ValueError, match="fresh"):
        corpus.prepare(manifest, destination)
    assert selected[0]["copy"].read_bytes() == b"edited working copy"


@pytest.mark.parametrize("invalid", ["../escape.docx", "document.exe"])
def test_selection_is_validated_before_any_outputs(source, invalid):
    original, manifest, destination = source
    path = original.parent / invalid
    path.write_bytes(b"must not copy")
    manifest["documents"].append({"id": "case-02", "path": invalid})
    with pytest.raises(ValueError):
        corpus.prepare(manifest, destination)
    assert not destination.exists()
    assert original.read_bytes() == b"storage-contract-fixture"


def test_source_cannot_be_output_directory(source):
    original, manifest, _ = source
    with pytest.raises(ValueError, match="separate"):
        corpus.prepare(manifest, original.parent / "outputs")
    assert sorted(p.name for p in original.parent.iterdir()) == [original.name]


def test_remote_server_is_rejected_before_reading_or_copying(source):
    _, manifest, destination = source
    with pytest.raises(ValueError, match="local"):
        corpus.run(manifest, destination, base_url="https://example.org")
    assert not destination.exists()


def test_native_checks_do_not_equate_editing_with_layout_or_invent_missing_observations():
    expected = {"pages": 1, "tables": 1, "normalized_text_sha256": "original", "heading_levels": {"3": 1}}
    actual = {"pages": 3, "tables": 1, "normalized_text_sha256": "changed"}
    checks = corpus.compare_word_inventory(expected, actual)
    assert checks == {"normalized_text_equal": False, "page_count_equal": False,
                      "table_count_equal": True, "heading_levels_equal": None}


def test_powerpoint_missing_geometry_does_not_become_verified():
    sample = {"slides": [{"top_level_boxes": [{"type": 17}]}]}
    result = corpus.compare_powerpoint_inventory(sample, sample)
    assert result["ordered_boxes_equal"] is None
    assert result["full_geometry_acceptance"] is None


def test_powerpoint_shape_types_remain_separate_from_coordinates():
    geometry = {"left": 1, "top": 2, "width": 3, "height": 4, "rotation": 0}
    first = {"slides": [{"top_level_boxes": [{**geometry, "type": 14}]}]}
    second = {"slides": [{"top_level_boxes": [{**geometry, "type": 17}]}]}
    result = corpus.compare_powerpoint_inventory(first, second)
    assert result["ordered_boxes_equal"] is True
    assert result["ordered_types_equal"] is False


@pytest.mark.parametrize("status", ["running", "interrupted"])
def test_observation_does_not_restart_or_cancel_live_task(status):
    class Client:
        def get(self, path):
            assert path == "/api/convert/status/contract-double"
            return self

        def raise_for_status(self):
            pass

        def json(self):
            return {"status": status}

    result = corpus.wait_task(Client(), {"status": "/api/convert/status/contract-double"}, timeout=0)
    assert result["status"] == status
    assert result.get("acceptance_observation_timeout", False) is (status == "running")


def test_explicit_text_cycle_keeps_the_source_format_and_original(source):
    original, manifest, destination = source
    manifest["documents"][0]["cycle_format"] = "txt"
    selected = corpus.prepare(manifest, destination)
    assert selected[0]["cycle_format"] == "txt"
    assert selected[0]["copy"].suffix == ".docx"
    assert original.read_bytes() == selected[0]["copy"].read_bytes()


def test_invalid_cycle_format_is_rejected_before_copying(source):
    _, manifest, destination = source
    manifest["documents"][0]["cycle_format"] = "../outside"
    with pytest.raises(ValueError, match="cycle format"):
        corpus.prepare(manifest, destination)
    assert not destination.exists()


def test_non_json_submission_failure_is_recorded_without_creating_an_artifact(tmp_path):
    import httpx

    source = tmp_path / "own.txt"
    source.write_text("Own QA source", encoding="utf-8")
    output = tmp_path / "result.json"
    transport = httpx.MockTransport(lambda request: httpx.Response(503, text="QA service unavailable"))
    with httpx.Client(transport=transport, base_url="http://127.0.0.1:8002", trust_env=False) as client:
        record = corpus.conversion(client, source, "model", output)
    assert record["submission_status"] == 503
    assert record["response"]["error"] == "Non-JSON HTTP response"
    assert record["result_sha256"] is None
    assert not output.exists()


@pytest.mark.parametrize("pid", [0, -1, True, 2**32])
def test_invalid_memory_pid_is_rejected_before_copying(source, pid):
    _, manifest, destination = source
    with pytest.raises(ValueError, match="PID"):
        corpus.run(manifest, destination, base_url="http://127.0.0.1:8002", server_pid=pid)
    assert not destination.exists()



def test_native_failure_preserves_web_evidence_and_source_hash(source, monkeypatch):
    import json
    import subprocess

    original, manifest, destination = source
    monkeypatch.setattr(corpus, "version", lambda name: "own-qa-version")
    def inspect(path):
        return {"inventory": {"normalized_text_sha256": "own-original"}}
    def native(path, edited=None):
        if edited is None:
            return inspect(path)
        raise subprocess.CalledProcessError(1, ["own-qa-native-driver"])
    def converted(client, path, target, output, **kwargs):
        output.write_bytes(b"own-qa-Web-result")
        return {"task_id": "own-qa-task", "result_sha256": corpus.digest(output), "status": {"status": "done"}}
    monkeypatch.setattr(corpus, "word_check", native)
    monkeypatch.setattr(corpus, "conversion", converted)
    with pytest.raises(subprocess.CalledProcessError):
        corpus.run(manifest, destination, base_url="http://127.0.0.1:8002", word=True)
    evidence = json.loads((destination / "acceptance.json").read_text())
    case = evidence["cases"][0]
    assert case["source_unchanged"] and case["source_sha256"] == corpus.digest(original)
    assert case["cycles"][0]["import"]["status"]["status"] == "done"
    assert case["cycles"][0]["export"]["result_sha256"]
    assert case["acceptance_error"] == {"type": "CalledProcessError", "returncode": 1}
    assert "target_program" not in case["cycles"][0]



def test_native_render_cannot_write_into_authorized_sources(source, monkeypatch):
    original, _, _ = source
    def unexpected(*args, **kwargs):
        pytest.fail("A rejected render must not start a native driver")
    monkeypatch.setattr(corpus.subprocess, "run", unexpected)
    with pytest.raises(ValueError, match="separate local"):
        corpus.target_program_check(original, program="powerpoint", render_directory=original.parent / "renders")
    assert not (original.parent / "renders").exists()


def test_native_render_rejects_an_existing_destination(source, monkeypatch):
    original, _, destination = source
    destination.mkdir(parents=True)
    def unexpected(*args, **kwargs):
        pytest.fail("An existing render must not start a native driver")
    monkeypatch.setattr(corpus.subprocess, "run", unexpected)
    with pytest.raises(ValueError, match="fresh native"):
        corpus.target_program_check(original, program="powerpoint", render_directory=destination)
    assert list(destination.iterdir()) == []
