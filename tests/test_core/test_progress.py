"""Тесты событий прогресса."""

from __future__ import annotations

from textalchemy.core.progress import ProgressEvent


def test_progress_event_to_dict():
    ev = ProgressEvent(kind="step_done", index=1, total=3, op="render.latex", name="tex", elapsed=0.5)
    d = ev.to_dict()
    assert d["kind"] == "step_done"
    assert d["index"] == 1
    assert d["total"] == 3
    assert d["op"] == "render.latex"
    assert d["error"] == ""


def test_progress_event_defaults():
    ev = ProgressEvent(kind="pipeline_start", index=0, total=0)
    assert ev.op == ""
    assert ev.name == ""
    assert ev.error == ""
    assert ev.elapsed == 0.0
