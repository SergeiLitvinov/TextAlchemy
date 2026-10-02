"""The template API must work without importing application services or touching files."""

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from opendoc.document_model import DocumentModel, Image, Paragraph, Section, TextRun

from textalchemy.core.exceptions import GenerateError
from textalchemy.generate.model_template import render_document_template as render_application
from textalchemy.templating import (
    TemplateError,
    TemplateField,
    TemplateImage,
    TemplateSchema,
    TemplateValueType,
    inspect_document_template,
    render_document_template,
)


def template(*texts):
    return DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun(text)]) for text in texts])])


def test_core_works_in_fresh_process_with_application_imports_blocked():
    probe = """
import importlib.abc
import json
import sys

class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("textalchemy.") and not (
            fullname == "textalchemy.templating" or fullname.startswith("textalchemy.templating.")
        ):
            raise AssertionError("Application dependency: " + fullname)
        if fullname.split(".")[0] in {"docx", "pptx", "fitz", "fastapi", "sqlalchemy", "yaml"}:
            raise AssertionError("Optional dependency: " + fullname)

sys.meta_path.insert(0, Boundary())
from opendoc.document_model import DocumentModel, Section, Paragraph, TextRun
from textalchemy.templating import render_document_template, TemplateSchema, TemplateField
model = DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun("{{ name }}")])])])
filled = render_document_template(model, {}, schema=TemplateSchema(fields=[TemplateField("name", default="Ada")]))
assert filled.sections[0].blocks[0].plain_text == "Ada"
print(json.dumps({"text": filled.sections[0].blocks[0].plain_text}))
"""
    result = subprocess.run([sys.executable, "-c", probe], text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == {"text": "Ada"}


def test_core_imports_stay_within_stdlib_jinja_opendoc_and_templating():
    source = Path(__file__).resolve().parents[2] / "src/textalchemy/templating"
    for path in source.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                modules = [node.module or ""]
            for module in modules:
                assert module.split(".")[0] in sys.stdlib_module_names | {"jinja2", "opendoc"}, (path.name, module)


def test_core_preserves_template_schema_and_data_during_nested_render():
    model = template(
        "{% for item in items %}", "{% if item.show %}", "{{ item.name }} {{ title }}", "{% endif %}", "{% endfor %}"
    )
    data = {"items": [{"show": True, "name": "A"}, {"show": False, "name": "B"}]}
    schema = TemplateSchema(fields=[TemplateField("items", TemplateValueType.ARRAY), TemplateField("title", default="Report")])
    original = copy.deepcopy((model, data, schema.to_dict()))
    inspection = inspect_document_template(model, schema)
    result = render_document_template(model, data, schema=schema)
    assert inspection.valid
    assert [block.plain_text for block in result.sections[0].blocks] == ["A Report"]
    assert (model, data, schema.to_dict()) == original


def test_core_images_use_injected_loader_and_do_not_read_paths(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Template engine read a file")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    image = TemplateImage(source="memory://brand.svg", media_type="image/svg+xml")
    model = template("{{ logo }}")
    with pytest.raises(TemplateError, match="requires an image_loader"):
        render_document_template(model, {"logo": image})
    loaded = []

    def loader(value):
        loaded.append(value)
        return b"<svg/>"

    result = render_document_template(model, {"logo": image}, image_loader=loader)
    assert loaded == [image]
    node = result.sections[0].blocks[0].content[0]
    assert isinstance(node, Image)
    assert result.resources[node.resource_id].data == b"<svg/>"
    assert not model.resources


def test_core_can_embed_image_bytes_without_any_loader():
    result = render_document_template(template("{{ logo }}"), {"logo": TemplateImage(data=b"png", media_type="image/png")})
    node = result.sections[0].blocks[0].content[0]
    assert result.resources[node.resource_id].data == b"png"


def test_core_bibliography_supports_consumer_formatter_without_application_types():
    result = render_document_template(
        template("{{ bibliography() }}"),
        {"references": [{"title": "Custom"}, None]},
        reference_formatter=lambda item: f"Reference: {item['title']}" if item else None,
    )
    assert [block.plain_text for block in result.sections[0].blocks] == ["[1] Reference: Custom"]


def test_application_adapter_preserves_disk_images_and_bibliography(tmp_path):
    path = tmp_path / "logo.svg"
    path.write_bytes(b"<svg/>")
    result = render_application(
        template("{{ logo }}", "{{ bibliography() }}"),
        {"logo": TemplateImage(source=path), "references": [{"authors": ["Ada"], "title": "Notes", "year": 2024}]},
    )
    node = result.sections[0].blocks[0].content[0]
    assert result.resources[node.resource_id].data == b"<svg/>"
    assert result.resources[node.resource_id].source == str(path)
    assert result.sections[0].blocks[1].plain_text == "[1] Ada Notes . – 2024"


@pytest.mark.parametrize("render, error", [(render_document_template, TemplateError), (render_application, GenerateError)])
def test_core_and_application_keep_distinct_error_contracts(render, error):
    model = template("{{ required }}")
    with pytest.raises(error, match="required value is missing"):
        render(model, {}, schema=TemplateSchema(fields=[TemplateField("required")]))
