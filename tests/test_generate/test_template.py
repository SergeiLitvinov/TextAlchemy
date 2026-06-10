import tempfile
from pathlib import Path

from textalchemy.generate import DocumentTemplate, TemplateEngine, generate_document, list_templates


def test_list_templates_empty():
    with tempfile.TemporaryDirectory() as tmp:
        templates = list_templates(tmp)
        assert templates == []


def test_template_engine_list_empty():
    with tempfile.TemporaryDirectory() as tmp:
        engine = TemplateEngine(tmp)
        assert engine.list_templates() == []


def test_generate_document_no_template():
    with tempfile.TemporaryDirectory() as tmp:
        import pytest
        with pytest.raises(Exception):
            generate_document("nonexistent", Path(tmp) / "out.docx", templates_dir=tmp)


def test_document_template():
    t = DocumentTemplate(name="test", description="Test template")
    assert t.name == "test"
    assert t.template_type == "docx"
