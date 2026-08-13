"""Контракты стадий и namespaced format extensions."""

from pathlib import Path

import pytest

from textalchemy.convert.stages import FormatExtension, StageContext, StageKind


def test_stage_context_exposes_cooperative_cancellation(tmp_path):
    context = StageContext(Path(tmp_path) / "out.pdf", cancelled=lambda: True)

    assert context.cancelled() is True
    assert StageKind.PARSE.value == "parse"
    assert StageKind.VERIFY.value == "verify"


def test_format_extension_roundtrip_is_namespaced():
    properties = FormatExtension("pptx", {"shape": {"id": "7"}}).apply_to({"role": "figure"})

    extension = FormatExtension.from_properties(properties, "pptx")
    assert properties["role"] == "figure"
    assert extension == FormatExtension("pptx", {"shape": {"id": "7"}})
    assert FormatExtension.from_properties(properties, "docx") is None


def test_format_extension_rejects_nested_namespace():
    with pytest.raises(ValueError):
        FormatExtension("pptx.shape", {})
