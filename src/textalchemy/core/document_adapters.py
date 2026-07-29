"""Совместимые адаптеры между старым ``Text`` и богатым ``DocumentModel``."""

from __future__ import annotations

from textalchemy.core.document_model import (
    Block as RichBlock,
)
from textalchemy.core.document_model import (
    DocumentModel,
    Formula,
    Image,
    Paragraph,
    Section,
    TableCell,
    TableRow,
    TextRun,
)
from textalchemy.core.document_model import (
    Table as RichTable,
)
from textalchemy.core.types import Block, BlockType, DocFormat, Table, Text


def text_to_document(text: Text) -> DocumentModel:
    """Поднять извлечённый ``Text`` в богатую модель без выдумывания оформления."""

    blocks: list[RichBlock] = []
    for block in text.blocks:
        properties = {"legacy_type": block.type.value, "level": block.level, "page": block.page, **block.meta}
        style_id = f"heading-{block.level}" if block.type is BlockType.HEADING and block.level else None
        blocks.append(Paragraph(content=[TextRun(block.text)], style_id=style_id, properties=properties))
    for table in text.tables:
        rows = [TableRow(cells=[TableCell(blocks=[Paragraph(content=[TextRun(cell)])]) for cell in row]) for row in table.rows]
        blocks.append(RichTable(rows=rows, properties={"page": table.page}))
    if not blocks and text.plain:
        blocks.append(Paragraph(content=[TextRun(text.plain)]))
    return DocumentModel(
        sections=[Section(blocks=blocks)],
        metadata={
            "language": text.language,
            "engine": text.engine,
            "warnings": list(text.warnings),
            "pages": text.pages,
        },
        source_format=text.source_format.value,
    )


def document_to_text(document: DocumentModel) -> Text:
    """Получить совместимый текстовый вид богатой модели для старого pipeline."""

    blocks: list[Block] = []
    tables: list[Table] = []
    plain_parts: list[str] = []

    def flatten(block: RichBlock) -> None:
        if isinstance(block, Paragraph):
            text = block.plain_text
            legacy_type = block.properties.get("legacy_type", BlockType.PARAGRAPH.value)
            try:
                block_type = BlockType(legacy_type)
            except ValueError:
                block_type = BlockType.PARAGRAPH
            legacy = Block(
                type=block_type,
                text=text,
                level=int(block.properties.get("level", 0)),
                page=int(block.properties.get("page", 0)),
            )
            blocks.append(legacy)
            if text:
                plain_parts.append(text)
        elif isinstance(block, RichTable):
            rows: list[list[str]] = []
            for row in block.rows:
                values: list[str] = []
                for cell in row.cells:
                    before = len(plain_parts)
                    cell_parts: list[str] = []
                    for child in cell.blocks:
                        if isinstance(child, Paragraph):
                            cell_parts.append(child.plain_text)
                        else:
                            flatten(child)
                    if len(plain_parts) > before:
                        del plain_parts[before:]
                    values.append("\n".join(part for part in cell_parts if part))
                rows.append(values)
            tables.append(Table(rows=rows, page=int(block.properties.get("page", 0))))
            plain_parts.extend(" | ".join(row) for row in rows)
        elif isinstance(block, Formula):
            value = block.fallback_text or block.value
            blocks.append(Block(type=BlockType.EQUATION, text=value))
            plain_parts.append(value)
        elif isinstance(block, Image) and block.alt_text:
            blocks.append(Block(type=BlockType.CAPTION, text=block.alt_text))
            plain_parts.append(block.alt_text)

    for section in document.sections:
        for block in section.blocks:
            flatten(block)

    raw_format = document.source_format or DocFormat.UNKNOWN.value
    try:
        source_format = DocFormat(raw_format)
    except ValueError:
        source_format = DocFormat.UNKNOWN
    return Text(
        blocks=blocks,
        tables=tables,
        plain="\n".join(plain_parts),
        language=str(document.metadata.get("language", "und")),
        source_format=source_format,
        engine=str(document.metadata.get("engine", "document-model")),
        warnings=list(document.metadata.get("warnings", [])),
        pages=int(document.metadata.get("pages", 0)),
    )


__all__ = ["document_to_text", "text_to_document"]
