"""Editable EPUB chapters, hyperlinks, media, and basic CSS."""

from io import BytesIO

import pytest

pytest.importorskip("bs4")
from PIL import Image as PillowImage

from tests.corpus.epub_fixture import write_epub_fixture
from textalchemy.convert.executor import ConversionExecutor, ConversionRequest
from textalchemy.core.document_codec import load_document, save_document
from textalchemy.core.document_model import Image, ResourceKind, TextRun
from textalchemy.core.types import DocFormat, Document
from textalchemy.formats.epub import read_epub_model
from textalchemy.pipeline.extract import extract_epub_model


def _rich_epub(path):
    buffer = BytesIO()
    PillowImage.new("RGB", (12, 8), "green").save(buffer, format="PNG")
    first = """<html><head><link href="../styles/main.css" rel="stylesheet" type="text/css"/></head>
      <body><h1 id="target">Первая</h1>
      <p class="note">До <a href="https://example.com"><strong>ссылки</strong></a></p>
      <p><img src="../images/picture.png" alt="Схема"/> после</p>
      <ol><li><span class="accent" style="font-style: italic">Пункт</span></li></ol></body></html>"""
    second = '<html><body><p><a href="first.xhtml#target">К первой</a></p></body></html>'
    write_epub_fixture(
        path,
        title="Rich book",
        language="ru",
        chapters=[("chapters/second.xhtml", "Second", second), ("chapters/first.xhtml", "First", first)],
        assets={
            "styles/main.css": (
                "text/css", b".accent { color: #123456; font-weight: 700 } p.note { font-size: 16px; background-color: #ffeecc }"
            ),
            "images/picture.png": ("image/png", buffer.getvalue()),
        },
    )


def test_spine_links_media_css_and_json_roundtrip(tmp_path):
    source = tmp_path / "rich.epub"
    _rich_epub(source)
    model = read_epub_model(source)
    assert model.source_format == "epub"
    assert model.metadata["title"] == "Rich book" and model.metadata["language"] == "ru"
    assert [section.properties["epub"]["title"] for section in model.sections] == ["Second", "First"]
    internal = model.sections[0].blocks[0].content[0]
    assert isinstance(internal, TextRun) and internal.link == "#epub-chapters-first.xhtml--target"
    blocks = model.sections[1].blocks
    external = next(item for block in blocks for item in block.content if isinstance(item, TextRun) and item.text == "ссылки")
    assert external.link == "https://example.com" and external.style.bold
    image = next(item for block in blocks for item in block.content if isinstance(item, Image))
    assert model.resources[image.resource_id].kind is ResourceKind.RASTER_IMAGE
    styled = next(item for block in blocks for item in block.content if isinstance(item, TextRun) and item.text == "Пункт")
    assert styled.style.color == "#123456" and styled.style.bold and styled.style.italic
    note = next(block for block in blocks if block.plain_text.startswith("До "))
    assert note.content[0].style.font_size.pt == 12 and note.content[0].style.background == "#ffeecc"
    assert {resource.kind for resource in model.resources.values()} == {ResourceKind.RASTER_IMAGE, ResourceKind.ATTACHMENT}
    saved = tmp_path / "model.json"
    save_document(model, saved)
    restored = load_document(saved)
    assert restored.sections[0].blocks[0].content[0].link == "#epub-chapters-first.xhtml--target"
    assert restored.resources[image.resource_id].data == model.resources[image.resource_id].data


def test_executor_pipeline_and_web_route(tmp_path):
    source, output = tmp_path / "book.epub", tmp_path / "book.json"
    _rich_epub(source)
    report = ConversionExecutor().execute(ConversionRequest(source, output, DocFormat.EPUB, DocFormat.MODEL))
    assert report.success and report.metrics["executed_steps"] == ["epub.model"]
    assert load_document(output).sections[0].properties["epub"]["title"] == "Second"
    result = extract_epub_model(doc=Document(source, DocFormat.EPUB, 0, ""))
    assert len(result.sections) == 2
    from textalchemy.web.services.conversion_catalog import available_conversions

    catalog = available_conversions(ConversionExecutor())
    epub_source = next(item for item in catalog["sources"] if item["format"] == "epub")
    assert {target["format"] for target in epub_source["targets"]} >= {"model", "html", "docx", "txt"}
    html = tmp_path / "book.html"
    report = ConversionExecutor().execute(ConversionRequest(source, html, DocFormat.EPUB, DocFormat.HTML))
    assert report.success, report.to_dict()
    rendered = html.read_text(encoding="utf-8")
    assert 'href="#epub-chapters-first.xhtml--target"' in rendered
    assert 'id="epub-chapters-first.xhtml--target"' in rendered
    assert "data:image/png;base64," in rendered
