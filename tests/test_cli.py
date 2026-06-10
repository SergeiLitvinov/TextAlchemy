import json
from pathlib import Path

import pytest

from textalchemy.__main__ import main


def test_cli_no_args(capsys):
    ret = main([])
    assert ret == 1
    captured = capsys.readouterr()
    assert "usage" in captured.out or "usage" in captured.err


def test_cli_version():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_cli_help_extract():
    with pytest.raises(SystemExit):
        main(["extract", "--help"])


def test_cli_help_convert():
    with pytest.raises(SystemExit):
        main(["convert", "--help"])


def test_cli_help_match():
    with pytest.raises(SystemExit):
        main(["match", "--help"])


def test_cli_help_gost():
    with pytest.raises(SystemExit):
        main(["gost", "--help"])


def test_cli_help_stats():
    with pytest.raises(SystemExit):
        main(["stats", "--help"])


def test_cli_help_export():
    with pytest.raises(SystemExit):
        main(["export", "--help"])


def test_cli_help_bibtex():
    with pytest.raises(SystemExit):
        main(["bibtex", "--help"])


def test_cli_help_init():
    with pytest.raises(SystemExit):
        main(["init", "--help"])


def test_cli_help_web():
    with pytest.raises(SystemExit):
        main(["web", "--help"])


def test_cli_help_generate():
    with pytest.raises(SystemExit):
        main(["generate", "--help"])


def test_cli_help_recognize():
    with pytest.raises(SystemExit):
        main(["recognize", "--help"])


# ── init ───────────────────────────────────────────

def test_cli_init(tmp_path):
    out = tmp_path / "test_config.json"
    ret = main(["init", "-o", str(out)])
    assert ret == 0
    assert out.exists()
    cfg = json.loads(out.read_text(encoding="utf-8"))
    assert "mode" in cfg


# ── extract ────────────────────────────────────────

def test_cli_extract_no_input(capsys):
    ret = main(["extract", "nonexistent.docx"])
    assert ret != 0


# ── convert ────────────────────────────────────────

def test_cli_convert_no_input(capsys):
    ret = main(["convert", "-i", "nonexistent_dir"])
    assert ret != 0


def test_cli_convert_dry_run(tmp_path):
    src = tmp_path / "pdfs"
    src.mkdir()
    ret = main(["convert", "-i", str(src), "--dry-run"])
    assert ret == 0


# ── stats ──────────────────────────────────────────

def test_cli_stats(capsys):
    ret = main(["stats"])
    assert ret == 0


def test_cli_stats_with_bibliography(tmp_path):
    bib = tmp_path / "bib.txt"
    bib.write_text("1. Author A. Title.", encoding="utf-8")
    ret = main(["stats", "-b", str(bib)])
    assert ret == 0


# ── export ─────────────────────────────────────────

def test_cli_export_json(tmp_path):
    bib = tmp_path / "input.txt"
    bib.write_text("1. Author A. Title.", encoding="utf-8")
    out = tmp_path / "out.json"
    ret = main(["export", "-i", str(bib), "-o", str(out), "-f", "json"])
    assert ret == 0
    assert out.exists()


def test_cli_export_markdown(tmp_path):
    bib = tmp_path / "input.txt"
    bib.write_text("1. Author A. Title.", encoding="utf-8")
    out = tmp_path / "out.md"
    ret = main(["export", "-i", str(bib), "-o", str(out), "-f", "markdown"])
    assert ret == 0
    assert out.exists()


def test_cli_export_gost(tmp_path):
    bib = tmp_path / "input.txt"
    bib.write_text("1. Author A. Title.", encoding="utf-8")
    out = tmp_path / "out.txt"
    ret = main(["export", "-i", str(bib), "-o", str(out), "-f", "gost"])
    assert ret == 0
    assert out.exists()


# ── gost ───────────────────────────────────────────

def test_cli_gost(tmp_path):
    bib = tmp_path / "input.txt"
    bib.write_text("1. Author A. Title.", encoding="utf-8")
    out = tmp_path / "out.txt"
    ret = main(["gost", "-i", str(bib), "-o", str(out)])
    assert ret == 0
    assert out.exists()


# ── match ──────────────────────────────────────────

def test_cli_match_dry_run(tmp_path):
    src = tmp_path / "literature_files"
    src.mkdir()
    bib = tmp_path / "bibliography.txt"
    bib.write_text("1. Author A. Title.", encoding="utf-8")
    ret = main(["match", "-s", str(src), "-b", str(bib), "--dry-run"])
    assert ret == 0


def test_cli_match_no_bibliography(tmp_path):
    src = tmp_path / "literature_files"
    src.mkdir()
    ret = main(["match", "-s", str(src)])
    # may find a bibliography file in CWD or return error
    assert ret in (0, 1)


def test_cli_match_json_report(tmp_path):
    src = tmp_path / "literature_files"
    src.mkdir()
    bib = tmp_path / "bibliography.txt"
    bib.write_text("1. Author A. Title.", encoding="utf-8")
    ret = main(["match", "-s", str(src), "-b", str(bib), "--json"])
    assert ret == 0


def test_cli_match_no_files(tmp_path):
    bib = tmp_path / "bibliography.txt"
    bib.write_text("1. Author A. Title.", encoding="utf-8")
    ret = main(["match", "-s", str(tmp_path), "-b", str(bib)])
    assert ret == 0


# ── generate ───────────────────────────────────────

def test_cli_generate_list(capsys):
    ret = main(["generate", "--list"])
    assert ret == 0


# ── recognize ──────────────────────────────────────

def test_cli_recognize_no_file(capsys):
    ret = main(["recognize", "nonexistent.pdf"])
    assert ret == 0


def test_cli_recognize_with_output(tmp_path):
    out = tmp_path / "out.txt"
    ret = main(["recognize", "nonexistent.pdf", "--output", str(out)])
    assert ret == 0
    assert out.exists()


# ── bibtex ─────────────────────────────────────────

def test_cli_bibtex(tmp_path):
    src = tmp_path / "literature_files"
    src.mkdir()
    out = tmp_path / "out.bib"
    ret = main(["bibtex", "-s", str(src), "-o", str(out)])
    assert ret == 0
    assert out.exists()


# ── unknown command ────────────────────────────────

def test_cli_unknown_command():
    with pytest.raises(SystemExit) as exc:
        main(["nonexistent"])
    assert exc.value.code == 2
