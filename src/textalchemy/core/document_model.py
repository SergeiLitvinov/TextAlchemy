"""Compatibility imports; document implementation lives in opendoc_model."""

from opendoc_model.document_model import (
    VECTOR_IMAGE_MEDIA_TYPES as VECTOR_IMAGE_MEDIA_TYPES,
)
from opendoc_model.document_model import (
    Block as Block,
)
from opendoc_model.document_model import (
    Box as Box,
)
from opendoc_model.document_model import (
    ConversionMode as ConversionMode,
)
from opendoc_model.document_model import (
    DocumentModel as DocumentModel,
)
from opendoc_model.document_model import (
    Formula as Formula,
)
from opendoc_model.document_model import (
    FormulaFormat as FormulaFormat,
)
from opendoc_model.document_model import (
    Image as Image,
)
from opendoc_model.document_model import (
    ImageCrop as ImageCrop,
)
from opendoc_model.document_model import (
    ImageProperties as ImageProperties,
)
from opendoc_model.document_model import (
    Inline as Inline,
)
from opendoc_model.document_model import (
    Length as Length,
)
from opendoc_model.document_model import (
    PackageGraph as PackageGraph,
)
from opendoc_model.document_model import (
    PackagePart as PackagePart,
)
from opendoc_model.document_model import (
    PackageRelationship as PackageRelationship,
)
from opendoc_model.document_model import (
    PageSettings as PageSettings,
)
from opendoc_model.document_model import (
    Paragraph as Paragraph,
)
from opendoc_model.document_model import (
    ParagraphProperties as ParagraphProperties,
)
from opendoc_model.document_model import (
    Provenance as Provenance,
)
from opendoc_model.document_model import (
    ProvenanceEvent as ProvenanceEvent,
)
from opendoc_model.document_model import (
    Resource as Resource,
)
from opendoc_model.document_model import (
    ResourceKind as ResourceKind,
)
from opendoc_model.document_model import (
    Section as Section,
)
from opendoc_model.document_model import (
    SectionProperties as SectionProperties,
)
from opendoc_model.document_model import (
    Table as Table,
)
from opendoc_model.document_model import (
    TableCell as TableCell,
)
from opendoc_model.document_model import (
    TableCellProperties as TableCellProperties,
)
from opendoc_model.document_model import (
    TableProperties as TableProperties,
)
from opendoc_model.document_model import (
    TableRow as TableRow,
)
from opendoc_model.document_model import (
    TableRowProperties as TableRowProperties,
)
from opendoc_model.document_model import (
    TextRun as TextRun,
)
from opendoc_model.document_model import (
    TextStyle as TextStyle,
)
from opendoc_model.document_model import (
    TextStyleProperties as TextStyleProperties,
)
from opendoc_model.document_model import (
    VisualSurrogate as VisualSurrogate,
)
from opendoc_model.document_model import (
    attach_visual_surrogate as attach_visual_surrogate,
)

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
