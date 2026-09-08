"""UTF-8 plain-text export with explicit flattening diagnostics."""

from pathlib import Path

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import Formula, Image, PageSettings, Paragraph, Table, TextRun, TextStyle
from textalchemy.core.io import atomic_write_bytes


def write_txt_model(document, output_path):
    report = ConversionReport(Path(output_path))
    losses = set()
    labels = {
        "styles": "оформление",
        "hyperlinks": "адреса ссылок",
        "formulas": "формулы",
        "images": "изображения",
        "tables": "таблицы",
        "sections": "секции",
        "resources": "встроенные ресурсы",
        "page_geometry": "геометрия страниц",
    }

    def loss(feature):
        if feature not in losses:
            losses.add(feature)
            report.add(
                IssueSeverity.LOSS, feature, f"В TXT не сохраняются: {labels[feature]}. Доступный основной текст перенесён."
            )

    def inline(item):
        if isinstance(item, TextRun):
            if item.style != TextStyle() or item.properties:
                loss("styles")
            if item.link:
                loss("hyperlinks")
            return item.text
        if isinstance(item, Formula):
            loss("formulas")
            return item.fallback_text or item.value
        if isinstance(item, Image):
            loss("images")
            return item.alt_text
        raise ValueError(f"Unsupported text element: {type(item).__name__}")

    def blocks(items):
        lines = []
        for block in items:
            if block.box is not None:
                loss("page_geometry")
            if isinstance(block, Paragraph):
                if block.style_id or block.alignment or block.properties:
                    loss("styles")
                lines.append("".join(inline(item) for item in block.content))
            elif isinstance(block, Table):
                loss("tables")
                lines.extend("\t".join(blocks(cell.blocks) for cell in row.cells) for row in block.rows)
            else:
                lines.append(inline(block))
        return "\n".join(lines)

    try:
        sections = []
        for section in document.sections:
            if section.page != PageSettings():
                loss("page_geometry")
            if any(
                (
                    section.headers,
                    section.footers,
                    section.first_page_headers,
                    section.first_page_footers,
                    section.even_page_headers,
                    section.even_page_footers,
                )
            ):
                report.add(IssueSeverity.LOSS, "running_content", "Колонтитулы не включены в основной текст TXT.")
            if section.properties:
                loss("sections")
            sections.append(blocks(section.blocks))
        if len(sections) > 1:
            loss("sections")
        if document.package or document.resources:
            loss("resources")
        if document.styles:
            loss("styles")
        text = "\n".join(sections)
        atomic_write_bytes(report.output_path, text.encode("utf-8"))
        report.metrics.update(characters=len(text), encoding="utf-8", line_separator="\n")
    except (OSError, ValueError, TypeError) as error:
        report.add(IssueSeverity.ERROR, "txt-write", str(error))
    return report
