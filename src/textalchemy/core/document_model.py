"""Богатая промежуточная модель для конвертации и генерации документов.

Модель не привязана к DOCX, PDF или PPTX. Импортёры должны сохранять в ней
семантику и геометрию исходного документа, а экспортёры — явно сообщать о
неподдержанных элементах вместо неявной потери данных.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeAlias


class ConversionMode(str, Enum):
    EDITABLE = "editable"
    FAITHFUL = "faithful"
    BALANCED = "balanced"


class ResourceKind(str, Enum):
    RASTER_IMAGE = "raster_image"
    VECTOR_IMAGE = "vector_image"
    FONT = "font"
    ATTACHMENT = "attachment"


class FormulaFormat(str, Enum):
    LATEX = "latex"
    MATHML = "mathml"
    OMML = "omml"


@dataclass
class Length:
    """Физическая длина в пунктах (1/72 дюйма)."""

    pt: float


@dataclass
class Box:
    """Геометрия элемента относительно страницы, в пунктах."""

    x: float
    y: float
    width: float
    height: float
    rotation: float = 0.0


@dataclass
class TextStyle:
    font_family: str | None = None
    font_size: Length | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    color: str | None = None
    background: str | None = None
    language: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Resource:
    id: str
    kind: ResourceKind
    media_type: str
    data: bytes | None = None
    source: str | None = None
    filename: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("resource id must not be empty")
        if self.data is None and self.source is None:
            raise ValueError("resource requires either data or source")


@dataclass
class TextRun:
    text: str
    style: TextStyle = field(default_factory=TextStyle)
    link: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Formula:
    value: str
    format: FormulaFormat
    display: bool = False
    fallback_text: str = ""
    box: Box | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Image:
    resource_id: str
    alt_text: str = ""
    box: Box | None = None
    properties: dict[str, Any] = field(default_factory=dict)


Inline: TypeAlias = TextRun | Formula | Image


@dataclass
class Paragraph:
    content: list[Inline] = field(default_factory=list)
    style_id: str | None = None
    alignment: str | None = None
    box: Box | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    @property
    def plain_text(self) -> str:
        parts: list[str] = []
        for item in self.content:
            if isinstance(item, TextRun):
                parts.append(item.text)
            elif isinstance(item, Formula):
                parts.append(item.fallback_text or item.value)
            elif isinstance(item, Image) and item.alt_text:
                parts.append(item.alt_text)
        return "".join(parts)


@dataclass
class TableCell:
    blocks: list[Block] = field(default_factory=list)
    row_span: int = 1
    column_span: int = 1
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class TableRow:
    cells: list[TableCell] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Table:
    rows: list[TableRow] = field(default_factory=list)
    style_id: str | None = None
    box: Box | None = None
    properties: dict[str, Any] = field(default_factory=dict)


Block: TypeAlias = Paragraph | Table | Formula | Image


@dataclass
class PageSettings:
    width: Length = field(default_factory=lambda: Length(595.28))
    height: Length = field(default_factory=lambda: Length(841.89))
    margin_top: Length = field(default_factory=lambda: Length(72.0))
    margin_right: Length = field(default_factory=lambda: Length(72.0))
    margin_bottom: Length = field(default_factory=lambda: Length(72.0))
    margin_left: Length = field(default_factory=lambda: Length(72.0))


@dataclass
class Section:
    blocks: list[Block] = field(default_factory=list)
    page: PageSettings = field(default_factory=PageSettings)
    headers: list[Block] = field(default_factory=list)
    footers: list[Block] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentModel:
    """Каноническое представление редактируемой и визуальной структуры."""

    sections: list[Section] = field(default_factory=list)
    resources: dict[str, Resource] = field(default_factory=dict)
    styles: dict[str, TextStyle] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    mode: ConversionMode = ConversionMode.BALANCED
    source_format: str | None = None
    version: int = 1

    def add_resource(self, resource: Resource) -> None:
        if resource.id in self.resources:
            raise ValueError(f"duplicate resource id: {resource.id}")
        self.resources[resource.id] = resource

    def validate(self) -> list[str]:
        """Вернуть диагностические сообщения о нарушенных ссылках модели."""

        errors: list[str] = []

        def check_block(block: Block, location: str) -> None:
            if isinstance(block, Image) and block.resource_id not in self.resources:
                errors.append(f"{location}: unknown resource {block.resource_id!r}")
            elif isinstance(block, Paragraph):
                for index, item in enumerate(block.content):
                    if isinstance(item, Image) and item.resource_id not in self.resources:
                        errors.append(f"{location}.content[{index}]: unknown resource {item.resource_id!r}")
            elif isinstance(block, Table):
                for row_index, row in enumerate(block.rows):
                    for cell_index, cell in enumerate(row.cells):
                        for block_index, child in enumerate(cell.blocks):
                            check_block(child, f"{location}.rows[{row_index}].cells[{cell_index}].blocks[{block_index}]")

        for section_index, section in enumerate(self.sections):
            for collection_name in ("blocks", "headers", "footers"):
                for block_index, block in enumerate(getattr(section, collection_name)):
                    check_block(block, f"sections[{section_index}].{collection_name}[{block_index}]")
        return errors


__all__ = [
    "Block",
    "Box",
    "ConversionMode",
    "DocumentModel",
    "Formula",
    "FormulaFormat",
    "Image",
    "Inline",
    "Length",
    "PageSettings",
    "Paragraph",
    "Resource",
    "ResourceKind",
    "Section",
    "Table",
    "TableCell",
    "TableRow",
    "TextRun",
    "TextStyle",
]
