"""CLI-тесты проверки DOCX-шаблонов."""

import json

import pytest
from docx import Document

from textalchemy.__main__ import main


def _write_template(path, text="{{ title }}"):
    document = Document()
    document.add_paragraph(text)
    document.save(path)


def test_cli_template_check_help():
    with pytest.raises(SystemExit) as caught:
        main(["template-check", "--help"])
    assert caught.value.code == 0


def test_cli_template_check_with_schema_and_data_json(tmp_path, capsys):
    template = tmp_path / "template.docx"
    schema = tmp_path / "schema.json"
    data = tmp_path / "data.json"
    _write_template(template, "Report: {{ title }}")
    schema.write_text(
        json.dumps({"fields": [{"name": "title", "type": "string"}], "allow_extra": False}),
        encoding="utf-8",
    )
    data.write_text(json.dumps({"title": "July"}), encoding="utf-8")

    result = main(
        ["template-check", str(template), "--schema", str(schema), "--data", str(data), "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["valid"] is True
    assert payload["data_valid"] is True
    assert payload["required_variables"] == ["title"]


def test_cli_template_check_fails_for_variable_missing_from_schema(tmp_path, capsys):
    template = tmp_path / "template.docx"
    schema = tmp_path / "schema.json"
    _write_template(template, "{{ undeclared }}")
    schema.write_text(json.dumps({"fields": []}), encoding="utf-8")

    result = main(["template-check", str(template), "--schema", str(schema), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert result == 1
    assert payload["valid"] is False
    assert any("undeclared" in error for error in payload["errors"])


def test_cli_template_check_fails_for_invalid_data_type(tmp_path, capsys):
    template = tmp_path / "template.docx"
    schema = tmp_path / "schema.yaml"
    data = tmp_path / "data.toml"
    _write_template(template)
    schema.write_text("fields:\n  - name: title\n    type: string\n", encoding="utf-8")
    data.write_text("title = 42\n", encoding="utf-8")

    result = main(
        ["template-check", str(template), "--schema", str(schema), "--data", str(data), "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 1
    assert payload["data_valid"] is False
    assert any("expected string" in error for error in payload["errors"])
