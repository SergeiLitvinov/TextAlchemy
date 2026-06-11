"""Тесты pipeline.runner."""
from __future__ import annotations

import json

import pytest

from textalchemy.core.registry import all_operations
from textalchemy.pipeline import extract as _extract_op  # noqa: F401
from textalchemy.pipeline import ingest as _ingest_op  # noqa: F401
from textalchemy.pipeline import match as _match_op  # noqa: F401
from textalchemy.pipeline import name as _name_op  # noqa: F401
from textalchemy.pipeline import render as _render_op  # noqa: F401
from textalchemy.pipeline.runner import load_pipeline, run_pipeline


def test_load_yaml(tmp_path):
    p = tmp_path / "pipe.yaml"
    p.write_text(
        "steps:\n"
        "  - op: render.latex\n"
        "    output: tex\n"
        "    params: {title: T}\n"
        "output: tex\n",
        encoding="utf-8",
    )
    spec = load_pipeline(p)
    assert spec["output"] == "tex"
    assert spec["steps"][0]["op"] == "render.latex"


def test_load_toml(tmp_path):
    p = tmp_path / "pipe.toml"
    p.write_text(
        'steps = [{op = "render.markdown", output = "md"}]\n'
        'output = "md"\n',
        encoding="utf-8",
    )
    spec = load_pipeline(p)
    assert spec["steps"][0]["op"] == "render.markdown"


def test_load_json(tmp_path):
    p = tmp_path / "pipe.json"
    p.write_text(
        json.dumps({"steps": [{"op": "render.markdown", "output": "md"}], "output": "md"}),
        encoding="utf-8",
    )
    spec = load_pipeline(p)
    assert spec["steps"][0]["op"] == "render.markdown"


def test_load_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_pipeline(tmp_path / "nope.yaml")


def test_run_simple_render(tmp_path):
    """Pipeline из одного шага render.markdown."""
    p = tmp_path / "pipe.yaml"
    p.write_text(
        "steps:\n"
        "  - op: render.markdown\n"
        "    output: md\n"
        "    params:\n"
        "      items: \"$bib\"\n"
        "output: md\n"
        "bib:\n"
        "  - index: 1\n"
        "    authors: [Иванов]\n"
        "    title: Hello\n",
        encoding="utf-8",
    )
    result = run_pipeline(p)
    assert result.ok, result.error
    assert "1. Иванов" in result.final


def test_run_chained_ingest_extract(tmp_path):
    """Pipeline: ingest.file → extract.text."""
    f = tmp_path / "a.txt"
    f.write_text("Hello world", encoding="utf-8")
    p = tmp_path / "pipe.yaml"
    p.write_text(
        f"steps:\n"
        f"  - op: ingest.file\n"
        f"    params: {{path: {str(f)!r}}}\n"
        f"    output: doc\n"
        f"  - op: extract.text\n"
        f"    input: doc\n"
        f"    output: text\n"
        f"output: text\n",
        encoding="utf-8",
    )
    result = run_pipeline(p)
    assert result.ok, result.error
    assert result.final.plain == "Hello world"
    assert result.final.source_format.value == "txt"


def test_run_unknown_op(tmp_path):
    p = tmp_path / "pipe.yaml"
    p.write_text("steps:\n  - op: does.not.exist\n", encoding="utf-8")
    result = run_pipeline(p)
    assert not result.ok
    assert "does.not.exist" in result.error
    assert result.steps[0].error is not None


def test_run_step_error(tmp_path):
    """Ошибка в шаге прерывает конвейер."""
    p = tmp_path / "pipe.yaml"
    p.write_text(
        "steps:\n"
        "  - op: ingest.file\n"
        "    params: {path: /no/such/file.pdf}\n"
        "    output: doc\n",
        encoding="utf-8",
    )
    result = run_pipeline(p)
    assert not result.ok
    assert result.steps[0].error is not None


def test_run_interpolation(tmp_path):
    """``params`` интерполируются через ctx."""
    f = tmp_path / "a.txt"
    f.write_text("Body content", encoding="utf-8")
    p = tmp_path / "pipe.yaml"
    p.write_text(
        "steps:\n"
        "  - op: ingest.file\n"
        "    output: doc\n"
        "    params:\n"
        f"      path: '{f}'\n"
        "  - op: extract.text\n"
        "    input: doc\n"
        "    output: text\n"
        "  - op: render.latex\n"
        "    input: text\n"
        "    output: out\n"
        "    params:\n"
        "      title: '{mytitle}'\n"
        "output: out\n"
        "mytitle: Injected Title\n",
        encoding="utf-8",
    )
    result = run_pipeline(p)
    assert result.ok, result.error
    assert "Injected Title" in result.final


def test_run_to_dict(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("Body", encoding="utf-8")
    p = tmp_path / "pipe.yaml"
    p.write_text(
        f"steps:\n"
        f"  - op: ingest.file\n"
        f"    output: doc\n"
        f"    params:\n"
        f"      path: {str(f)!r}\n"
        f"  - op: extract.text\n"
        f"    input: doc\n"
        f"    output: text\n"
        f"  - op: render.latex\n"
        f"    input: text\n"
        f"    output: tex\n"
        f"    params:\n"
        f"      title: T\n",
        encoding="utf-8",
    )
    result = run_pipeline(p)
    d = result.to_dict()
    assert d["ok"] is True
    assert d["final"]  # строка, не None
    assert len(d["steps"]) == 3
    assert d["steps"][2]["op"] == "render.latex"


def test_all_operations_in_registry():
    """Sanity check: все ожидаемые операции зарегистрированы."""
    ids = {s.id for s in all_operations()}
    expected = {
        "ingest.file", "extract.text", "match.bibliography",
        "render.latex", "render.latex.pandoc", "render.docx",
        "render.bibtex", "render.gost", "render.markdown", "render.json",
        "name.from_match",
    }
    assert expected <= ids
