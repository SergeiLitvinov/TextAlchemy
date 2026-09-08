"""Экспорт DocumentModel в PDF через встроенный HTML-layout PyMuPDF."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textalchemy.convert.color_preflight import preflight_colors
from textalchemy.convert.font_preflight import prepare_fonts
from textalchemy.convert.html_writer import _HtmlRenderer
from textalchemy.convert.pdf_resources import PdfHtmlRenderer
from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import Block, DocumentModel, Formula, FormulaFormat, Paragraph, Section, Table
from textalchemy.fonts.html_embedding import archived_font_stylesheet


def write_pdf_model(document: DocumentModel, output_path: str | Path) -> ConversionReport:
    """Записать модель в PDF, сохранив размеры секций и многостраничный поток."""

    import fitz

    output = Path(output_path)
    report = ConversionReport(output)
    document = prepare_fonts(document, report)
    preflight_colors(document, report, target="pdf")
    target = fitz.open()
    totals = {"paragraphs": 0, "tables": 0, "images": 0, "formulas": 0, "pages": 0}

    try:
        for section_index, section in enumerate(document.sections or [Section()]):
            section_pdf, renderer = _render_section(document, section, section_index, report)
            totals["pages"] += section_pdf.page_count
            for key in ("paragraphs", "tables", "images", "formulas"):
                totals[key] += renderer.metrics[key]
            target.insert_pdf(section_pdf)
            section_pdf.close()
        _set_metadata(target, document.metadata)
        from textalchemy.core.artifacts import ArtifactWorkspace
        from textalchemy.core.io import atomic_copy

        with ArtifactWorkspace(prefix="textalchemy_pdf_writer_") as workspace:
            staged = workspace.artifact_path("output.pdf")
            target.save(staged, garbage=4, deflate=True)
            workspace.validate_artifact(staged)
            atomic_copy(staged, output)
    except Exception as error:  # noqa: BLE001 - backend failures must be represented in the report
        report.add(IssueSeverity.ERROR, "pdf-write", str(error))
        return report
    finally:
        target.close()

    try:
        with fitz.open(output) as check:
            if check.page_count != totals["pages"] or check.page_count == 0:
                report.add(IssueSeverity.ERROR, "pdf-validation", "written PDF has an invalid page count")
            _verify_pdf_font_embedding(check, document, report)
    except Exception as error:  # noqa: BLE001 - validation is part of the diagnostic boundary
        report.add(IssueSeverity.ERROR, "pdf-validation", str(error))
    report.metrics.update(totals)
    report.metrics["sections"] = len(document.sections or [Section()])
    report.metrics["resources"] = len(document.resources)
    return report


def _render_section(
    document: DocumentModel,
    section: Section,
    section_index: int,
    report: ConversionReport,
) -> tuple[Any, _HtmlRenderer]:
    import fitz

    section_model = DocumentModel(
        sections=[section],
        resources=document.resources,
        styles=document.styles,
        metadata=document.metadata,
        mode=document.mode,
        source_format=document.source_format,
        version=document.version,
    )
    renderer = PdfHtmlRenderer(section_model, report)
    main_html = renderer._blocks(section.blocks, f"sections[{section_index}].blocks")
    header_html = renderer._blocks(section.headers, f"sections[{section_index}].headers")
    footer_html = renderer._blocks(section.footers, f"sections[{section_index}].footers")
    _report_mathml_fallback(section.blocks, report, f"sections[{section_index}].blocks")
    _report_mathml_fallback(section.headers, report, f"sections[{section_index}].headers")
    _report_mathml_fallback(section.footers, report, f"sections[{section_index}].footers")

    page = section.page
    media_box = fitz.Rect(0, 0, page.width.pt, page.height.pt)
    content_box = fitz.Rect(
        page.margin_left.pt,
        page.margin_top.pt,
        page.width.pt - page.margin_right.pt,
        page.height.pt - page.margin_bottom.pt,
    )

    def rect_function(_rect_number: int, _filled: Any) -> tuple[Any, Any, Any]:
        return media_box, content_box, fitz.Identity

    from textalchemy.core.artifacts import ArtifactWorkspace

    with ArtifactWorkspace(prefix="textalchemy_pdf_fonts_") as font_workspace:
        font_styles = archived_font_stylesheet(document, font_workspace, report)
        css = (
            font_styles
            + "\n"
            + renderer.stylesheet(include_page_rules=False)
            + "\nhtml, body { background: white; } body { margin: 0; }"
        )
        archive = fitz.Archive(str(font_workspace.path))
        story = fitz.Story(html=main_html or "<p></p>", user_css=css, archive=archive)

        def page_function(_page_number: int, _mediabox: Any, device: Any, after: int) -> None:
            if after:
                return
            if header_html:
                header_box = fitz.Rect(
                    page.margin_left.pt,
                    max(2, page.margin_top.pt * 0.15),
                    page.width.pt - page.margin_right.pt,
                    max(4, page.margin_top.pt - 4),
                )
                _draw_fixed_story(header_html, css, header_box, device, report, "header", archive=archive)
            if footer_html:
                footer_box = fitz.Rect(
                    page.margin_left.pt,
                    min(page.height.pt - 4, page.height.pt - page.margin_bottom.pt + 4),
                    page.width.pt - page.margin_right.pt,
                    page.height.pt - 2,
                )
                _draw_fixed_story(footer_html, css, footer_box, device, report, "footer", archive=archive)

        section_pdf = story.write_with_links(rect_function, pagefn=page_function)
    if isinstance(section_pdf, fitz.Document):
        return section_pdf, renderer
    return fitz.open(stream=section_pdf.read(), filetype="pdf"), renderer


def _verify_pdf_font_embedding(pdf: Any, document: DocumentModel, report: ConversionReport) -> None:
    from textalchemy.fonts.embedding import collect_font_usages

    expected = [usage for usage in collect_font_usages(document) if usage.embeddable]
    observed: set[str] = set()
    for page in pdf:
        for font in page.get_fonts(full=True):
            if font and int(font[0]) > 0:
                observed.update(_font_token(str(value)) for value in font[3:5] if value)
    verified = 0
    for usage in expected:
        requested = _font_token(usage.family)
        if any(requested in name or name in requested for name in observed if name):
            verified += 1
        else:
            report.add(
                IssueSeverity.LOSS,
                "font-embedding",
                f"PDF output does not contain the requested embedded font {usage.family!r}",
            )
    metrics = report.metrics.setdefault("font_embedding", {"target": "pdf"})
    metrics["verified_faces"] = verified
    metrics["pdf_fonts"] = sorted(observed)


def _font_token(value: str) -> str:
    token = value.split("+", 1)[-1]
    return "".join(character for character in token.casefold() if character.isalnum())


def _draw_fixed_story(
    html: str,
    css: str,
    rectangle: Any,
    device: Any,
    report: ConversionReport,
    feature: str,
    *,
    archive: Any = None,
) -> None:
    import fitz

    story = fitz.Story(html=html, user_css=css, archive=archive)
    more, _filled = story.place(rectangle)
    story.draw(device)
    if more:
        report.add(IssueSeverity.LOSS, feature, f"{feature} content was clipped because it exceeds the page margin")


def _report_mathml_fallback(blocks: list[Block], report: ConversionReport, location: str) -> None:
    for index, block in enumerate(blocks):
        block_location = f"{location}[{index}]"
        if isinstance(block, Formula) and block.format is FormulaFormat.MATHML:
            report.add(
                IssueSeverity.LOSS,
                "formula",
                "MathML is flattened by the PDF HTML backend; exact mathematical layout is not guaranteed",
                block_location,
            )
        elif isinstance(block, Paragraph):
            for inline_index, item in enumerate(block.content):
                if isinstance(item, Formula) and item.format is FormulaFormat.MATHML:
                    report.add(
                        IssueSeverity.LOSS,
                        "formula",
                        "MathML is flattened by the PDF HTML backend; exact mathematical layout is not guaranteed",
                        f"{block_location}.content[{inline_index}]",
                    )
        elif isinstance(block, Table):
            for row_index, row in enumerate(block.rows):
                for cell_index, cell in enumerate(row.cells):
                    _report_mathml_fallback(
                        cell.blocks,
                        report,
                        f"{block_location}.rows[{row_index}].cells[{cell_index}].blocks",
                    )


def _set_metadata(document: Any, metadata: dict[str, Any]) -> None:
    current = document.metadata
    for name in ("title", "author", "subject", "keywords", "creator", "producer"):
        value = metadata.get(name)
        if value is not None:
            current[name] = str(value)
    current.setdefault("producer", "TextAlchemy / PyMuPDF")
    document.set_metadata(current)


__all__ = ["write_pdf_model"]
