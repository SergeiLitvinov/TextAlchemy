"""DOCX → Text.

Единый ридер DOCX; раньше было две копии (extract/text.py и
organize/extractors/docx.py).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Union

from textalchemy.core.document_model import (
    Block as RichBlock,
)
from textalchemy.core.document_model import (
    Box,
    ConversionMode,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    Length,
    PageSettings,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
)
from textalchemy.core.document_model import (
    Table as RichTable,
)
from textalchemy.core.types import Block, BlockType, DocFormat, Table, Text


def read_docx(path: Union[str, Path], *, include_tables: bool = True) -> Text:
    from docx import Document  # type: ignore[import-not-found]

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    doc = Document(str(p))
    blocks: list[Block] = []
    tables: list[Table] = []
    plain: list[str] = []

    for para in doc.paragraphs:
        t = para.text
        blocks.append(Block(type=BlockType.PARAGRAPH, text=t))
        if t:
            plain.append(t)

    if include_tables:
        for tbl in doc.tables:
            rows = [[cell.text for cell in row.cells] for row in tbl.rows]
            tables.append(Table(rows=rows))
            for row in rows:
                plain.append(" | ".join(row))

    return Text(
        blocks=blocks,
        tables=tables,
        plain="\n".join(plain),
        source_format=DocFormat.DOCX,
        engine="python-docx",
    )


def read_docx_model(
    path: Union[str, Path],
    *,
    mode: ConversionMode = ConversionMode.BALANCED,
) -> DocumentModel:
    """Импортировать DOCX в богатую модель с оформлением и ресурсами."""

    from docx import Document as OpenDocument  # type: ignore[import-not-found]
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    document = OpenDocument(str(source))
    model = DocumentModel(
        mode=mode,
        source_format=DocFormat.DOCX.value,
        metadata=_document_metadata(document, source),
    )

    section_blocks: list[list[RichBlock]] = [[]]
    for item in document.iter_inner_content():
        if isinstance(item, DocxParagraph):
            section_blocks[-1].append(_paragraph_to_model(item, model))
            if item._p.pPr is not None and item._p.pPr.sectPr is not None:
                section_blocks.append([])
        elif isinstance(item, DocxTable):
            section_blocks[-1].append(_table_to_model(item, model))

    if len(section_blocks) > 1 and not section_blocks[-1]:
        section_blocks.pop()
    for index, blocks in enumerate(section_blocks):
        source_section = document.sections[min(index, len(document.sections) - 1)]
        model.sections.append(
            Section(
                blocks=blocks,
                page=_page_settings(source_section),
                headers=_container_blocks(source_section.header, model),
                footers=_container_blocks(source_section.footer, model),
                properties={"start_type": str(source_section.start_type)},
            )
        )
    return model


def _document_metadata(document: Any, source: Path) -> dict[str, Any]:
    props = document.core_properties
    return {
        "title": props.title or "",
        "subject": props.subject or "",
        "author": props.author or "",
        "keywords": props.keywords or "",
        "comments": props.comments or "",
        "created": props.created.isoformat() if props.created else None,
        "modified": props.modified.isoformat() if props.modified else None,
        "source_name": source.name,
    }


def _page_settings(section: Any) -> PageSettings:
    def points(value: Any, default: float) -> Length:
        return Length(float(value.pt)) if value is not None else Length(default)

    return PageSettings(
        width=points(section.page_width, 595.28),
        height=points(section.page_height, 841.89),
        margin_top=points(section.top_margin, 72.0),
        margin_right=points(section.right_margin, 72.0),
        margin_bottom=points(section.bottom_margin, 72.0),
        margin_left=points(section.left_margin, 72.0),
    )


def _container_blocks(container: Any, model: DocumentModel) -> list[RichBlock]:
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    result: list[RichBlock] = []
    for item in container.iter_inner_content():
        if isinstance(item, DocxParagraph):
            result.append(_paragraph_to_model(item, model))
        elif isinstance(item, DocxTable):
            result.append(_table_to_model(item, model))
    return result


def _paragraph_to_model(paragraph: Any, model: DocumentModel) -> Paragraph:
    from docx.text.hyperlink import Hyperlink
    from docx.text.run import Run
    from lxml import etree

    content: list[TextRun | Formula | Image] = []
    for item in paragraph.iter_inner_content():
        if isinstance(item, Run):
            if item.text:
                content.append(TextRun(item.text, style=_run_style(item)))
            content.extend(_run_images(item, model))
        elif isinstance(item, Hyperlink):
            for run in item.runs:
                if run.text:
                    content.append(TextRun(run.text, style=_run_style(run), link=item.url or None))
                content.extend(_run_images(run, model))

    for math in paragraph._p.xpath(".//m:oMath | .//m:oMathPara"):
        xml = etree.tostring(math, encoding="unicode")
        if not any(isinstance(item, Formula) and item.value == xml for item in content):
            content.append(
                Formula(
                    value=xml,
                    format=FormulaFormat.OMML,
                    display=etree.QName(math).localname == "oMathPara",
                    fallback_text="".join(math.itertext()),
                )
            )

    alignment = paragraph.alignment
    alignment_name = alignment.name.lower() if alignment is not None else None
    style_id = paragraph.style.style_id if paragraph.style is not None else None
    properties: dict[str, Any] = {}
    if paragraph.style is not None:
        properties["style_name"] = paragraph.style.name
    paragraph_format = paragraph.paragraph_format
    for name in ("left_indent", "right_indent", "first_line_indent", "space_before", "space_after", "line_spacing"):
        value = getattr(paragraph_format, name)
        if hasattr(value, "pt"):
            properties[f"{name}_pt"] = float(value.pt)
        elif value is not None:
            properties[name] = float(value)
    return Paragraph(content=content, style_id=style_id, alignment=alignment_name, properties=properties)


def _run_style(run: Any) -> TextStyle:
    font = run.font
    color = None
    if font.color is not None and font.color.rgb is not None:
        color = f"#{font.color.rgb}"
    return TextStyle(
        font_family=font.name,
        font_size=Length(float(font.size.pt)) if font.size is not None else None,
        bold=font.bold,
        italic=font.italic,
        underline=bool(font.underline) if font.underline is not None else None,
        color=color,
        language=_run_language(run),
        properties={"style_id": run.style.style_id if run.style is not None else None},
    )


def _run_language(run: Any) -> str | None:
    from docx.oxml.ns import qn

    language = run._r.xpath("./w:rPr/w:lang")
    if not language:
        return None
    return language[0].get(qn("w:val"))


def _run_images(run: Any, model: DocumentModel) -> list[Image]:
    from docx.oxml.ns import qn

    images: list[Image] = []
    for blip in run._r.xpath(".//a:blip"):
        relationship_id = blip.get(qn("r:embed"))
        if not relationship_id:
            continue
        image_part = run.part.related_parts.get(relationship_id)
        if image_part is None or not hasattr(image_part, "blob"):
            continue
        data = image_part.blob
        digest = hashlib.sha256(data).hexdigest()
        resource_id = f"image-{digest[:16]}"
        if resource_id not in model.resources:
            content_type = image_part.content_type
            vector_types = {"image/svg+xml", "image/x-emf", "image/x-wmf"}
            kind = ResourceKind.VECTOR_IMAGE if content_type in vector_types else ResourceKind.RASTER_IMAGE
            model.add_resource(
                Resource(
                    id=resource_id,
                    kind=kind,
                    media_type=content_type,
                    data=data,
                    filename=Path(str(image_part.partname)).name,
                    properties={"sha256": digest},
                )
            )
        extent = run._r.xpath(".//wp:extent")
        box = None
        if extent:
            box = Box(0.0, 0.0, float(extent[0].get("cx", 0)) / 12700, float(extent[0].get("cy", 0)) / 12700)
        doc_properties = run._r.xpath(".//wp:docPr")
        alt_text = ""
        properties: dict[str, Any] = {}
        if doc_properties:
            alt_text = doc_properties[0].get("descr") or doc_properties[0].get("title") or ""
            properties["name"] = doc_properties[0].get("name")
        images.append(Image(resource_id=resource_id, alt_text=alt_text, box=box, properties=properties))
    return images


def _table_to_model(table: Any, model: DocumentModel) -> RichTable:
    from docx.oxml.ns import qn

    rows: list[TableRow] = []
    for row in table.rows:
        cells: list[TableCell] = []
        seen_cells: set[int] = set()
        for cell in row.cells:
            cell_identity = id(cell._tc)
            if cell_identity in seen_cells:
                continue
            seen_cells.add(cell_identity)
            grid_span = cell._tc.xpath("./w:tcPr/w:gridSpan")
            column_span = int(grid_span[0].get(qn("w:val"), "1")) if grid_span else 1
            vertical_merge = cell._tc.xpath("./w:tcPr/w:vMerge")
            properties: dict[str, Any] = {}
            if vertical_merge:
                properties["vertical_merge"] = vertical_merge[0].get(qn("w:val"), "continue")
            cells.append(
                TableCell(
                    blocks=_container_blocks(cell, model),
                    column_span=column_span,
                    properties=properties,
                )
            )
        rows.append(TableRow(cells=cells))
    style_id = table.style.style_id if table.style is not None else None
    properties = {"style_name": table.style.name} if table.style is not None else {}
    return RichTable(rows=rows, style_id=style_id, properties=properties)


__all__ = ["read_docx", "read_docx_model"]
