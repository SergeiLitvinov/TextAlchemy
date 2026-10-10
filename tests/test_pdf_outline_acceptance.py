"""Own PDF outline acceptance through public application and model contracts."""

from dataclasses import replace

import pymupdf
import pytest
from opendoc_model import Outline, get_outline, load_document, save_document, set_outline

from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.quality_policy import QualityPolicy
from textalchemy.core.types import DocFormat


def outline_pdf(path, rotation):
    with pymupdf.open() as pdf:
        for index in range(2):
            page = pdf.new_page(width=595, height=842)
            page.insert_text((100, 150), f"Own outline page {index + 1}")
            page.set_cropbox(pymupdf.Rect(50, 70, 545, 772))
            page.set_rotation(rotation if index else 0)
        pdf.set_toc([
            [1, "Own chapter", 1, {"kind": pymupdf.LINK_GOTO, "page": 0,
                                    "to": pymupdf.Point(100, 150), "zoom": 1.25}],
            [2, "Own detail", 2, {"kind": pymupdf.LINK_GOTO, "page": 1,
                                   "to": pymupdf.Point(100, 150), "zoom": 1.5}],
        ])
        pdf.save(path)
    return path


def native_outline(path):
    with pymupdf.open(path) as pdf:
        return [(level, title, page, dest["kind"], dest["page"],
                 tuple(dest["to"]), dest["zoom"])
                for level, title, page, dest in pdf.get_toc(False)]


def convert(source, target, input_format, output_format, *, policy=None):
    report = ConversionExecutor().execute(ConversionRequest(
        source, target, input_format, output_format, quality_policy=policy,
    ))
    assert report.success, report.issues
    return report


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_outline_points_and_native_edit_survive_two_cycles(tmp_path, rotation):
    source = outline_pdf(tmp_path / "source.pdf", rotation)
    original = source.read_bytes()
    expected = native_outline(source)
    current = source
    for cycle in range(2):
        model_path = tmp_path / f"cycle-{cycle}.json"
        output = tmp_path / f"cycle-{cycle}.pdf"
        convert(current, model_path, DocFormat.PDF, DocFormat.MODEL)
        outline = get_outline(load_document(model_path))
        assert outline is not None and len(outline.entries) == 2
        assert outline.entries[1].parent_id == outline.entries[0].id
        assert all(entry.target.kind == "page" and entry.target.point is not None
                   for entry in outline.entries)
        convert(model_path, output, DocFormat.MODEL, DocFormat.PDF)
        assert native_outline(output) == expected
        if cycle == 0:
            edited = tmp_path / "native-edit.pdf"
            with pymupdf.open(output) as pdf:
                pdf.set_toc_item(1, title="Own native edit")
                pdf.save(edited)
            expected = native_outline(edited)
            assert expected[1][1] == "Own native edit"
            current = edited
    assert source.read_bytes() == original


def test_explicit_outline_removal_is_not_resurrected(tmp_path):
    source = outline_pdf(tmp_path / "source.pdf", 90)
    model_path = tmp_path / "source.json"
    convert(source, model_path, DocFormat.PDF, DocFormat.MODEL)
    model = load_document(model_path)
    assert get_outline(model).entries
    set_outline(model, Outline(entries=()))
    save_document(model, model_path)
    current = model_path
    for cycle in range(2):
        output = tmp_path / f"removed-{cycle}.pdf"
        current_model = tmp_path / f"removed-{cycle}.json"
        convert(current, output, DocFormat.MODEL, DocFormat.PDF)
        with pymupdf.open(output) as pdf:
            assert pdf.get_toc() == []
        convert(output, current_model, DocFormat.PDF, DocFormat.MODEL)
        outline = get_outline(load_document(current_model))
        assert outline is None or not outline.entries
        current = current_model


def test_unsafe_outline_target_rejects_publication_atomically(tmp_path):
    source = outline_pdf(tmp_path / "source.pdf", 0)
    model_path = tmp_path / "source.json"
    convert(source, model_path, DocFormat.PDF, DocFormat.MODEL)
    model = load_document(model_path)
    outline = get_outline(model)
    first = outline.entries[0]
    first = replace(first, target=replace(first.target, kind="external", target_id=None,
                                         point=None, zoom=None, uri="ftp://example.invalid/own"))
    set_outline(model, replace(outline, entries=(first, *outline.entries[1:])))
    save_document(model, model_path)
    output = tmp_path / "previous.pdf"
    output.write_bytes(b"previous artifact")
    report = ConversionExecutor().execute(ConversionRequest(
        model_path, output, DocFormat.MODEL, DocFormat.PDF,
        # Admit the one retained import loss so the writer evaluates the target.
        quality_policy=QualityPolicy(1),
    ))
    assert not report.success
    assert any(issue.feature == "pdf.outline-target" and issue.location
               for issue in report.issues)
    assert output.read_bytes() == b"previous artifact"
