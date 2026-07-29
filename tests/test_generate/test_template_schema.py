"""Тесты схемы данных и предварительной инспекции шаблонов."""

import pytest

from textalchemy.core.document_model import DocumentModel, FormulaFormat, Paragraph, Section, TextRun
from textalchemy.core.exceptions import GenerateError
from textalchemy.generate import (
    TemplateField,
    TemplateFormula,
    TemplateImage,
    TemplateSchema,
    TemplateValueType,
    inspect_document_template,
    load_template_data,
    load_template_schema,
    render_document_template,
    validate_template_data,
)


def _paragraph(text: str) -> Paragraph:
    return Paragraph(content=[TextRun(text)])


def test_schema_applies_nested_defaults_and_preserves_source_data():
    schema = TemplateSchema(
        fields=[
            TemplateField("title", TemplateValueType.STRING),
            TemplateField("options.locale", TemplateValueType.STRING, required=False, default="ru-RU"),
        ],
        allow_extra=False,
    )
    source = {"title": "Report"}

    result = validate_template_data(schema, source)

    assert result == {"title": "Report", "options": {"locale": "ru-RU"}}
    assert source == {"title": "Report"}


def test_schema_reports_all_validation_errors_together():
    schema = TemplateSchema(
        fields=[
            TemplateField("title", TemplateValueType.STRING),
            TemplateField("count", TemplateValueType.INTEGER),
        ],
        allow_extra=False,
    )

    with pytest.raises(GenerateError) as caught:
        validate_template_data(schema, {"count": "many", "unexpected": True})

    message = str(caught.value)
    assert "title: required value is missing" in message
    assert "count: expected integer" in message
    assert "unexpected: unexpected value" in message


def test_schema_dict_roundtrip_preserves_explicit_default():
    raw = {
        "fields": {
            "enabled": {"type": "boolean", "required": False, "default": False},
            "items": {"type": "array"},
        },
        "allow_extra": False,
    }

    schema = TemplateSchema.from_dict(raw)

    assert schema.to_dict() == {
        "fields": [
            {"name": "enabled", "type": "boolean", "required": False, "description": "", "default": False},
            {"name": "items", "type": "array", "required": True, "description": ""},
        ],
        "allow_extra": False,
    }


def test_inspection_finds_variables_and_excludes_loop_local():
    template = DocumentModel(
        metadata={"title": "{{ title }}"},
        sections=[
            Section(
                blocks=[
                    _paragraph("{% if enabled %}"),
                    _paragraph("{% for item in items %}"),
                    _paragraph("{{ item.name }} / {{ suffix }}"),
                    _paragraph("{% endfor %}"),
                    _paragraph("{% endif %}"),
                ]
            )
        ],
    )

    inspection = inspect_document_template(template)

    assert inspection.valid is True
    assert inspection.required_variables == ["enabled", "items", "suffix", "title"]
    assert "item" not in inspection.references
    assert inspection.references["title"] == ["metadata.title"]


def test_inspection_reports_structure_syntax_and_schema_mismatch():
    template = DocumentModel(
        sections=[Section(blocks=[_paragraph("{{ malformed "), _paragraph("{% if enabled %}"), _paragraph("x")])]
    )
    schema = TemplateSchema(fields=[TemplateField("unused"), TemplateField("enabled", TemplateValueType.BOOLEAN)])

    inspection = inspect_document_template(template, schema)

    assert inspection.valid is False
    assert any("unexpected end" in error.lower() for error in inspection.errors)
    assert any("endif" in error for error in inspection.errors)
    assert any("unused" in warning for warning in inspection.warnings)


def test_render_uses_schema_defaults_before_jinja():
    template = DocumentModel(sections=[Section(blocks=[_paragraph("Language: {{ language }}")])])
    schema = TemplateSchema(fields=[TemplateField("language", TemplateValueType.STRING, required=False, default="Russian")])

    result = render_document_template(template, {}, schema=schema)

    assert result.sections[0].blocks[0].plain_text == "Language: Russian"


def test_load_schema_and_data_from_supported_formats(tmp_path):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(
        '{"fields": [{"name": "title", "type": "string"}], "allow_extra": false}',
        encoding="utf-8",
    )
    data_path = tmp_path / "data.yaml"
    data_path.write_text("title: Report\nitems:\n  - one\n", encoding="utf-8")

    schema = load_template_schema(schema_path)
    data = load_template_data(data_path)

    assert schema.fields[0].name == "title"
    assert schema.allow_extra is False
    assert data == {"title": "Report", "items": ["one"]}


def test_schema_converts_declarative_image_and_formula_values(tmp_path):
    image_path = tmp_path / "diagram.png"
    image_path.write_bytes(b"png")
    schema = TemplateSchema(
        fields=[
            TemplateField("diagram", TemplateValueType.IMAGE),
            TemplateField("equation", TemplateValueType.FORMULA),
        ]
    )

    result = validate_template_data(
        schema,
        {
            "diagram": {"source": str(image_path), "alt_text": "Diagram"},
            "equation": {"value": "x^2", "format": "latex", "display": True},
        },
    )

    assert result["diagram"] == TemplateImage(source=str(image_path), alt_text="Diagram")
    assert result["equation"] == TemplateFormula(value="x^2", format=FormulaFormat.LATEX, display=True)
