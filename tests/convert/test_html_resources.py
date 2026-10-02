"""Снимок ресурсов и сохранность результата при отказе HTML-экспорта."""

from pathlib import Path

import pytest

from textalchemy.convert.html_resources import HtmlResourceStage
from textalchemy.convert.html_writer import write_html_model
from textalchemy.convert.stages import StageContext
from textalchemy.core.document_model import DocumentModel, Image, Paragraph, Resource, ResourceKind, Section


@pytest.mark.parametrize("existing", [False, True])
def test_missing_image_does_not_publish_or_replace_html(tmp_path: Path, existing: bool) -> None:
    output = tmp_path / "result.html"
    if existing:
        output.write_bytes(b"Previous valid result")
    model = DocumentModel(sections=[Section(blocks=[Image("missing")])])
    report = write_html_model(model, output)
    assert not report.success
    assert report.metrics["resource_preparation"]["accepted"] is False
    if existing:
        assert output.read_bytes() == b"Previous valid result"
    else:
        assert not output.exists()


def test_resource_stage_freezes_repeated_external_image_without_mutating_model(tmp_path: Path) -> None:
    source = tmp_path / "picture.svg"
    raw = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    source.write_bytes(raw)
    resource = Resource("picture", ResourceKind.VECTOR_IMAGE, "image/svg+xml", source=source)
    model = DocumentModel(
        resources={"picture": resource},
        sections=[
            Section(
                blocks=[
                    Image("picture"),
                    Paragraph(content=[Image("picture")]),
                ]
            )
        ],
    )
    prepared = HtmlResourceStage().execute(model, StageContext(tmp_path / "out.html"))
    assert prepared.report.success
    assert prepared.report.metrics["resource_preparation"] == {
        "stage": "html.resources",
        "references": 2,
        "requested": 1,
        "resolved": 1,
        "bytes": len(raw),
        "accepted": True,
    }
    source.unlink()
    report = write_html_model(prepared.value, tmp_path / "out.html")
    assert report.success and report.metrics["images"] == 2
    assert model.resources["picture"] is resource and resource.data is None
    assert prepared.value.resources["picture"].data == raw


@pytest.mark.parametrize("media_type, source", [("text/plain", None), ("image/png", "absent.png")])
def test_resource_preparation_rejects_invalid_media_or_missing_source(
    tmp_path: Path, media_type: str, source: str | None
) -> None:
    model = DocumentModel(
        resources={
            "picture": Resource(
                "picture",
                ResourceKind.RASTER_IMAGE,
                media_type,
                source=tmp_path / source if source else None,
                data=b"content" if source is None else None,
            )
        },
        sections=[Section(headers=[Image("picture")])],
    )
    output = tmp_path / "out.html"
    output.write_bytes(b"Previous result")
    report = write_html_model(model, output)
    assert not report.success
    assert report.issues[0].location == "sections[0].headers[0]"
    assert output.read_bytes() == b"Previous result"
