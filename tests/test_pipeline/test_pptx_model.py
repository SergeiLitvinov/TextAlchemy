"""Тесты pipeline-операции extract.pptx_model."""

from pathlib import Path

import pytest

from textalchemy.core.document_model import DocumentModel, Table
from textalchemy.core.registry import all_operations
from textalchemy.core.types import DocFormat, Document
from textalchemy.pipeline.extract import extract_pptx_model  # noqa: F401
from textalchemy.pipeline.ingest import ingest_file  # noqa: F401

CORPUS_PPTX = Path(__file__).resolve().parent.parent / "corpus" / "office" / "libreoffice-scientific-slides.pptx"


class TestExtractPptxModelRegistry:
    def test_registered(self):
        ids = {spec.id for spec in all_operations()}
        assert "extract.pptx_model" in ids


class TestExtractPptxModel:
    def test_not_pptx_returns_empty_model(self):
        doc = Document(path=Path("/fake.txt"), format=DocFormat.TXT, size=0, sha256="")
        model = extract_pptx_model(doc=doc)
        assert isinstance(model, DocumentModel)
        assert model.sections == []
        assert "not a PPTX" in model.metadata.get("warnings", [""])[0]

    def test_requires_keyword_document(self):
        with pytest.raises(TypeError):
            extract_pptx_model()  # type: ignore[call-arg]

    def test_extracts_sections_and_blocks(self):
        doc = ingest_file(path=CORPUS_PPTX)
        model = extract_pptx_model(doc=doc)

        assert isinstance(model, DocumentModel)
        assert len(model.sections) == 2
        assert model.source_format == "pptx"
        tables = [block for block in model.sections[0].blocks if isinstance(block, Table)]
        assert len(tables) == 1
        assert model.validate() == []

    def test_pipeline_runner_chain(self):
        pipeline = {
            "steps": [
                {"op": "ingest.file", "output": "doc", "params": {"path": str(CORPUS_PPTX)}},
                {"op": "extract.pptx_model", "input": "doc", "output": "model"},
            ],
            "output": "model",
        }
        from textalchemy.pipeline.runner import run_pipeline

        result = run_pipeline(pipeline)
        assert result.error is None
        model = result.final
        assert isinstance(model, DocumentModel)
        assert len(model.sections) == 2
