"""Compatibility imports; document implementation lives in opendoc_model."""

from opendoc_model.properties import (
    PROPERTY_SCHEMA_VERSION as PROPERTY_SCHEMA_VERSION,
)
from opendoc_model.properties import (
    ImageProperties as ImageProperties,
)
from opendoc_model.properties import (
    ParagraphProperties as ParagraphProperties,
)
from opendoc_model.properties import (
    SectionProperties as SectionProperties,
)
from opendoc_model.properties import (
    TableCellProperties as TableCellProperties,
)
from opendoc_model.properties import (
    TableProperties as TableProperties,
)
from opendoc_model.properties import (
    TableRowProperties as TableRowProperties,
)
from opendoc_model.properties import (
    TextStyleProperties as TextStyleProperties,
)
from opendoc_model.properties import (
    VersionedProperties as VersionedProperties,
)
from opendoc_model.properties import (
    WrapPoint as WrapPoint,
)
from opendoc_model.properties import (
    WrapPolygon as WrapPolygon,
)

__all__ = [
    "ImageProperties",
    "ParagraphProperties",
    "PROPERTY_SCHEMA_VERSION",
    "SectionProperties",
    "TableCellProperties",
    "TableProperties",
    "TableRowProperties",
    "TextStyleProperties",
    "VersionedProperties",
    "WrapPoint",
    "WrapPolygon",
]
