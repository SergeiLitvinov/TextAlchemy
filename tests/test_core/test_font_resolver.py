"""Тесты детерминированного font resolver и glyph-аудита."""

from pathlib import Path

from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import DocumentModel, Paragraph, Section, TextRun, TextStyle
from textalchemy.fonts import FontFace, FontResolver, prepare_document_fonts
from textalchemy.fonts.html_embedding import embedded_font_stylesheet


def _face(family: str, *, width=5, glyphs="abcАБВ", weight=400, italic=False):
    return FontFace(
        family=family,
        path=Path(f"/{family}.ttf"),
        width_class=width,
        weight=weight,
        italic=italic,
        glyphs=frozenset(map(ord, glyphs)),
    )


def test_resolver_prefers_exact_family_and_reports_missing_glyphs():
    resolver = FontResolver([_face("Arial"), _face("Liberation Sans")])

    resolution = resolver.resolve("Arial", "abcЖ")

    assert resolution.exact is True
    assert resolution.resolved == "Arial"
    assert resolution.missing_glyphs == ("Ж",)


def test_resolver_substitution_is_metric_aware_and_deterministic():
    resolver = FontResolver([
        _face("Wide Serif", width=9),
        _face("Liberation Sans", width=5),
        _face("Another Sans", width=5),
    ])

    first = resolver.resolve("Missing Sans", "abc")
    second = resolver.resolve("Missing Sans", "abc")

    assert first == second
    assert first.resolved == "Another Sans"  # deterministic family-name tie break
    assert first.exact is False


def test_prepare_document_fonts_returns_copy_and_machine_readable_report():
    original = DocumentModel(sections=[Section(blocks=[
        Paragraph(content=[TextRun("abcЖ", style=TextStyle(font_family="Missing Sans"))])
    ])])
    resolver = FontResolver([_face("Liberation Sans", glyphs="abc")])

    prepared, report = prepare_document_fonts(original, resolver)

    original_run = original.sections[0].blocks[0].content[0]
    prepared_run = prepared.sections[0].blocks[0].content[0]
    assert original_run.style.font_family == "Missing Sans"
    assert prepared_run.style.font_family == "Liberation Sans"
    assert prepared_run.style.properties["font_resolution"]["requested"] == "Missing Sans"
    assert report.to_dict()["substitution_count"] == 1
    assert report.to_dict()["fonts_with_missing_glyphs"] == 1


def test_prepare_document_fonts_accumulates_missing_glyphs_for_shared_style():
    document = DocumentModel(
        sections=[
            Section(
                blocks=[
                    Paragraph(content=[TextRun("aЖ", style=TextStyle(font_family="Demo"))]),
                    Paragraph(content=[TextRun("aЮ", style=TextStyle(font_family="Demo"))]),
                ]
            )
        ]
    )
    _, report = prepare_document_fonts(document, FontResolver([_face("Demo", glyphs="a")]))

    assert report.resolutions["Demo|0|0"].missing_glyphs == ("Ж", "Ю")


def test_prepare_document_fonts_uses_one_substitute_for_the_whole_style():
    document = DocumentModel(
        sections=[
            Section(
                blocks=[
                    Paragraph(content=[TextRun("aЖ", style=TextStyle(font_family="Missing Sans"))]),
                    Paragraph(content=[TextRun("aЮ", style=TextStyle(font_family="Missing Sans"))]),
                ]
            )
        ]
    )
    registry = FontResolver([_face("Alpha Sans", glyphs="aЖ"), _face("Beta Sans", glyphs="aЮ")])

    prepared, report = prepare_document_fonts(document, registry)

    families = [block.content[0].style.font_family for block in prepared.sections[0].blocks]
    assert families == ["Alpha Sans", "Alpha Sans"]
    assert report.resolutions["Missing Sans|0|0"].missing_glyphs == ("Ю",)


def test_html_embedding_uses_resolved_font_and_records_metrics(tmp_path):
    font_path = tmp_path / "Demo.ttf"
    font_path.write_bytes(b"font-bytes")
    document = DocumentModel(
        sections=[Section(blocks=[Paragraph(content=[TextRun("abc", style=TextStyle(font_family="Missing Sans"))])])]
    )
    registry = FontResolver([FontFace("Demo Sans", font_path, glyphs=frozenset(map(ord, "abc")))])
    prepared, _ = prepare_document_fonts(document, registry)
    conversion_report = ConversionReport(tmp_path / "result.html")

    stylesheet = embedded_font_stylesheet(prepared, conversion_report)

    assert '@font-face { font-family: "Demo Sans"' in stylesheet
    assert "Zm9udC1ieXRlcw==" in stylesheet
    assert conversion_report.metrics["font_embedding"] == {
        "embedded_faces": 1,
        "source_bytes": 10,
        "embedded_bytes": 10,
        "target": "html",
    }
