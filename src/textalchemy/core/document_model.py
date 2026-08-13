"""Богатая промежуточная модель для конвертации и генерации документов.

Модель не привязана к DOCX, PDF или PPTX. Импортёры должны сохранять в ней
семантику и геометрию исходного документа, а экспортёры — явно сообщать о
неподдержанных элементах вместо неявной потери данных.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeAlias

from textalchemy.core.color import ColorLike
from textalchemy.core.properties import (
    ImageProperties,
    ParagraphProperties,
    SectionProperties,
    TableCellProperties,
    TableProperties,
    TableRowProperties,
    TextStyleProperties,
)


class ConversionMode(str, Enum):
    EDITABLE = "editable"
    FAITHFUL = "faithful"
    BALANCED = "balanced"


class ResourceKind(str, Enum):
    RASTER_IMAGE = "raster_image"
    VECTOR_IMAGE = "vector_image"
    FONT = "font"
    ATTACHMENT = "attachment"


VECTOR_IMAGE_MEDIA_TYPES = frozenset({"image/svg+xml", "image/x-emf", "image/x-wmf", "image/emf", "image/wmf"})


class FormulaFormat(str, Enum):
    LATEX = "latex"
    MATHML = "mathml"
    OMML = "omml"


@dataclass
class ProvenanceEvent:
    """One traceable transformation applied to a model element or resource."""

    operation: str
    detail: str = ""
    fallback_reason: str | None = None


@dataclass
class Provenance:
    """Stable origin pointer plus an append-only transformation history."""

    source_format: str
    source_path: str | None = None
    page: int | None = None
    object_id: str | None = None
    package_part: str | None = None
    events: list[ProvenanceEvent] = field(default_factory=list)

    def transformed(self, operation: str, *, detail: str = "", fallback_reason: str | None = None) -> Provenance:
        return Provenance(
            source_format=self.source_format,
            source_path=self.source_path,
            page=self.page,
            object_id=self.object_id,
            package_part=self.package_part,
            events=[*self.events, ProvenanceEvent(operation, detail, fallback_reason)],
        )


@dataclass
class VisualSurrogate:
    """Visual companion retained beside a native editable representation."""

    resource_id: str
    reason: str
    media_type: str | None = None
    fidelity: float | None = None

    def __post_init__(self) -> None:
        if not self.resource_id:
            raise ValueError("visual surrogate resource id must not be empty")
        if not self.reason:
            raise ValueError("visual surrogate reason must not be empty")
        if self.fidelity is not None and not 0.0 <= self.fidelity <= 1.0:
            raise ValueError("visual surrogate fidelity must be between 0 and 1")


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
class ImageCrop:
    """Обрезка изображения как доля от исходного размера для каждой стороны."""

    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0


@dataclass
class TextStyle:
    font_family: str | None = None
    font_size: Length | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    superscript: bool | None = None
    subscript: bool | None = None
    color: ColorLike | None = None
    background: ColorLike | None = None
    language: str | None = None
    properties: TextStyleProperties = field(default_factory=TextStyleProperties)

    def __post_init__(self) -> None:
        if not isinstance(self.properties, TextStyleProperties):
            self.properties = TextStyleProperties(self.properties)


@dataclass
class Resource:
    id: str
    kind: ResourceKind
    media_type: str
    data: bytes | None = None
    source: str | None = None
    filename: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("resource id must not be empty")
        if self.data is None and self.source is None:
            raise ValueError("resource requires either data or source")


@dataclass
class PackagePart:
    """Opaque package part preserved for a format-aware round-trip."""

    name: str
    media_type: str
    data: bytes

    def __post_init__(self) -> None:
        if not self.name.startswith("/"):
            raise ValueError("package part name must be absolute")


@dataclass
class PackageRelationship:
    """Directed relationship between package parts or to an external target."""

    id: str
    relationship_type: str
    source: str
    target: str
    external: bool = False


@dataclass
class PackageGraph:
    """Format-specific package topology kept outside semantic resources."""

    format: str
    root: str = "/word/document.xml"
    parts: dict[str, PackagePart] = field(default_factory=dict)
    relationships: list[PackageRelationship] = field(default_factory=list)

    def add_part(self, part: PackagePart) -> None:
        if part.name in self.parts and self.parts[part.name] != part:
            raise ValueError(f"duplicate package part: {part.name}")
        self.parts[part.name] = part

    def add_relationship(self, relationship: PackageRelationship) -> None:
        key = (relationship.source, relationship.id)
        if any((item.source, item.id) == key for item in self.relationships):
            raise ValueError(f"duplicate package relationship: {relationship.source}:{relationship.id}")
        self.relationships.append(relationship)

    def related_part(self, source: str, relationship_type: str) -> PackagePart | None:
        relationship = next(
            (
                item
                for item in self.relationships
                if item.source == source and item.relationship_type == relationship_type and not item.external
            ),
            None,
        )
        return self.parts.get(relationship.target) if relationship is not None else None

    def validate(self) -> list[str]:
        errors: list[str] = []
        seen: set[tuple[str, str]] = set()
        for relationship in self.relationships:
            key = (relationship.source, relationship.id)
            if key in seen:
                errors.append(f"duplicate relationship {relationship.source}:{relationship.id}")
            seen.add(key)
            if relationship.source not in self.parts and relationship.source != self.root:
                errors.append(f"unknown relationship source {relationship.source!r}")
            if not relationship.external and relationship.target not in self.parts:
                errors.append(f"unknown relationship target {relationship.target!r}")
        return errors


@dataclass
class TextRun:
    text: str
    style: TextStyle = field(default_factory=TextStyle)
    link: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None
    visual_surrogate: VisualSurrogate | None = None


@dataclass
class Formula:
    value: str
    format: FormulaFormat
    display: bool = False
    fallback_text: str = ""
    box: Box | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None
    visual_surrogate: VisualSurrogate | None = None


@dataclass
class Image:
    resource_id: str
    alt_text: str = ""
    box: Box | None = None
    properties: ImageProperties = field(default_factory=ImageProperties)
    crop: ImageCrop | None = None
    provenance: Provenance | None = None
    visual_surrogate: VisualSurrogate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.properties, ImageProperties):
            self.properties = ImageProperties(self.properties)


Inline: TypeAlias = TextRun | Formula | Image


@dataclass
class Paragraph:
    content: list[Inline] = field(default_factory=list)
    style_id: str | None = None
    alignment: str | None = None
    box: Box | None = None
    properties: ParagraphProperties = field(default_factory=ParagraphProperties)
    provenance: Provenance | None = None
    visual_surrogate: VisualSurrogate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.properties, ParagraphProperties):
            self.properties = ParagraphProperties(self.properties)

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
    properties: TableCellProperties = field(default_factory=TableCellProperties)

    def __post_init__(self) -> None:
        if not isinstance(self.properties, TableCellProperties):
            self.properties = TableCellProperties(self.properties)


@dataclass
class TableRow:
    cells: list[TableCell] = field(default_factory=list)
    properties: TableRowProperties = field(default_factory=TableRowProperties)

    def __post_init__(self) -> None:
        if not isinstance(self.properties, TableRowProperties):
            self.properties = TableRowProperties(self.properties)


@dataclass
class Table:
    rows: list[TableRow] = field(default_factory=list)
    style_id: str | None = None
    box: Box | None = None
    properties: TableProperties = field(default_factory=TableProperties)
    provenance: Provenance | None = None
    visual_surrogate: VisualSurrogate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.properties, TableProperties):
            self.properties = TableProperties(self.properties)


Block: TypeAlias = Paragraph | Table | Formula | Image


def attach_visual_surrogate(
    element: Paragraph | Table | Formula | Image,
    resource: Resource,
    *,
    reason: str,
    fidelity: float | None = None,
    operation: str = "fallback.visual-surrogate",
) -> None:
    """Attach a visual companion and record why the native representation is insufficient."""
    element.visual_surrogate = VisualSurrogate(
        resource_id=resource.id,
        reason=reason,
        media_type=resource.media_type,
        fidelity=fidelity,
    )
    if element.provenance is not None:
        element.provenance = element.provenance.transformed(
            operation,
            detail=f"linked visual surrogate {resource.id}",
            fallback_reason=reason,
        )


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
    first_page_headers: list[Block] = field(default_factory=list)
    first_page_footers: list[Block] = field(default_factory=list)
    even_page_headers: list[Block] = field(default_factory=list)
    even_page_footers: list[Block] = field(default_factory=list)
    properties: SectionProperties = field(default_factory=SectionProperties)
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.properties, SectionProperties):
            self.properties = SectionProperties(self.properties)


@dataclass
class DocumentModel:
    """Каноническое представление редактируемой и визуальной структуры."""

    sections: list[Section] = field(default_factory=list)
    resources: dict[str, Resource] = field(default_factory=dict)
    styles: dict[str, TextStyle] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    package: PackageGraph | None = None
    mode: ConversionMode = ConversionMode.BALANCED
    source_format: str | None = None
    version: int = 2

    def add_resource(self, resource: Resource) -> None:
        if resource.id in self.resources:
            raise ValueError(f"duplicate resource id: {resource.id}")
        self.resources[resource.id] = resource

    def validate(self) -> list[str]:
        """Вернуть диагностические сообщения о нарушенных ссылках модели."""

        errors: list[str] = []

        def check_image(image: Image, location: str) -> None:
            if image.resource_id not in self.resources:
                errors.append(f"{location}: unknown resource {image.resource_id!r}")
            fallback_id = image.properties.fallback_resource_id
            if fallback_id is not None and fallback_id not in self.resources:
                errors.append(f"{location}: unknown fallback resource {fallback_id!r}")

        def check_surrogate(block: Block | Inline, location: str) -> None:
            surrogate = getattr(block, "visual_surrogate", None)
            if surrogate is not None and surrogate.resource_id not in self.resources:
                errors.append(f"{location}: unknown visual surrogate resource {surrogate.resource_id!r}")

        def check_block(block: Block, location: str) -> None:
            check_surrogate(block, location)
            if isinstance(block, Image):
                check_image(block, location)
            elif isinstance(block, Paragraph):
                for index, item in enumerate(block.content):
                    check_surrogate(item, f"{location}.content[{index}]")
                    if isinstance(item, Image):
                        check_image(item, f"{location}.content[{index}]")
            elif isinstance(block, Table):
                for row_index, row in enumerate(block.rows):
                    for cell_index, cell in enumerate(row.cells):
                        for block_index, child in enumerate(cell.blocks):
                            check_block(child, f"{location}.rows[{row_index}].cells[{cell_index}].blocks[{block_index}]")

        for section_index, section in enumerate(self.sections):
            for collection_name in (
                "blocks",
                "headers",
                "footers",
                "first_page_headers",
                "first_page_footers",
                "even_page_headers",
                "even_page_footers",
            ):
                for block_index, block in enumerate(getattr(section, collection_name)):
                    check_block(block, f"sections[{section_index}].{collection_name}[{block_index}]")
        if self.package is not None:
            errors.extend(f"package: {error}" for error in self.package.validate())
        return errors


__all__ = [
    "Block",
    "attach_visual_surrogate",
    "Box",
    "ConversionMode",
    "DocumentModel",
    "Formula",
    "FormulaFormat",
    "Image",
    "ImageCrop",
    "ImageProperties",
    "Inline",
    "Length",
    "PageSettings",
    "PackageGraph",
    "PackagePart",
    "PackageRelationship",
    "Paragraph",
    "Provenance",
    "ProvenanceEvent",
    "ParagraphProperties",
    "Resource",
    "ResourceKind",
    "Section",
    "SectionProperties",
    "Table",
    "TableCell",
    "TableCellProperties",
    "TableProperties",
    "TableRow",
    "TableRowProperties",
    "TextRun",
    "TextStyle",
    "VisualSurrogate",
    "TextStyleProperties",
    "VECTOR_IMAGE_MEDIA_TYPES",
]
