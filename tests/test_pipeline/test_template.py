"""Тесты pipeline-операции шаблонизатора."""

from textalchemy.core.document_model import DocumentModel, Paragraph, Section, TextRun
from textalchemy.core.registry import get
from textalchemy.pipeline.runner import run_pipeline
from textalchemy.pipeline.template import render_template


def test_template_operation_registered():
    spec = get("template.render")
    assert spec.func is render_template
    assert spec.input_param == "document"


def test_template_operation_runs_and_serializes_in_pipeline_result():
    document = DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun("Hello {{ name }}")])])])

    result = run_pipeline(
        {
            "document": document,
            "steps": [
                {
                    "op": "template.render",
                    "input": "document",
                    "output": "rendered",
                    "params": {"data": {"name": "Pipeline"}},
                }
            ],
            "output": "rendered",
        }
    )

    assert result.ok is True
    assert result.final.sections[0].blocks[0].plain_text == "Hello Pipeline"
    serialized = result.to_dict()["final"]
    assert serialized["format"] == "textalchemy.document"
