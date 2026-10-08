"""Real PowerPoint series/text edits between two actual Web conversions."""

import os
import sys
import uuid

import pytest

from tests import test_web_m4_completion as fixtures
from tests.corpus.pptx_acceptance import write_chart_presentation
from textalchemy.web.queue import task_queue
from tools.acceptance.corpus import ROOT, compare_powerpoint_inventory, digest, target_program_check

m4_client = fixtures.m4_client


@pytest.mark.skipif(sys.platform != "win32" or os.getenv("TEXTALCHEMY_POWERPOINT_ACCEPTANCE") != "1",
                    reason="Requires installed PowerPoint and explicit local acceptance run")
def test_native_chart_edit_and_geometry_two_web_cycles(m4_client, tmp_path):
    client, _ = m4_client
    source = tmp_path / "own-chart.pptx"
    write_chart_presentation(source)
    original_hash = digest(source)
    baseline = target_program_check(source, program="powerpoint")
    assert baseline["inventory"]["slide_count"] == 1
    expected = baseline["inventory"]
    for cycle in range(1, 3):
        imported = client.post("/api/convert", files={"file": (source.name, source.read_bytes())},
                               data={"target_format": "model"})
        assert imported.status_code == 200
        assert task_queue.wait_idle(timeout=30)
        model = client.get(imported.json()["result"])
        assert model.status_code == 200
        exported = client.post("/api/convert", files={"file": ("model.json", model.content)},
                               data={"target_format": "pptx"})
        assert exported.status_code == 200
        assert task_queue.wait_idle(timeout=30)
        result = client.get(exported.json()["result"])
        assert result.status_code == 200
        native = tmp_path / f"cycle-{cycle}.pptx"
        edited = tmp_path / f"edited-{cycle}.pptx"
        native.write_bytes(result.content)
        original = native.read_bytes()
        evidence = target_program_check(native, edited, program="powerpoint")
        assert all(evidence["checks"].values()), evidence
        assert evidence["chart_series_observation"]["observed_first_value"] == 3 + cycle
        assert evidence["chart_series_observation"]["embedded_workbook_edit"] is None
        assert evidence["before"]["slides"][0]["charts"] == 1
        comparison = compare_powerpoint_inventory(expected, evidence["before"])
        assert comparison["text_equal"] and comparison["charts_equal"] and comparison["ordered_boxes_equal"], comparison
        assert comparison["full_geometry_acceptance"] is None
        assert native.read_bytes() == original
        expected = evidence["after"]
        source = edited
    assert digest(tmp_path / "own-chart.pptx") == original_hash


@pytest.mark.skipif(sys.platform != "win32" or os.getenv("TEXTALCHEMY_POWERPOINT_ACCEPTANCE") != "1",
                    reason="Requires installed PowerPoint and explicit local acceptance run")
def test_real_native_png_render_keeps_input_and_records_every_slide(tmp_path):
    from PIL import Image

    source = tmp_path / "own-render.pptx"
    write_chart_presentation(source)
    original = digest(source)
    render = ROOT / ".textalchemy/acceptance/native-render-tests" / uuid.uuid4().hex
    record = target_program_check(source, program="powerpoint", render_directory=render)
    assert digest(source) == original == record["artifact_sha256"]
    native = record["native_render"]
    assert native["basis"] == "PowerPoint-Slide.Export-PNG" and native["scope"] == "all-slides-before-QA-edit"
    assert len(native["files"]) == record["inventory"]["slide_count"] == 1
    item = native["files"][0]
    assert item["slide"] == 1 and digest(render / item["file"]) == item["sha256"]
    with Image.open(render / item["file"]) as image:
        assert image.size == (native["width"], native["height"]) and image.width == 1280
