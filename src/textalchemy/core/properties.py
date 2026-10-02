"""Compatibility imports; document implementation lives in opendoc."""

from opendoc.properties import (
    PROPERTY_SCHEMA_VERSION as PROPERTY_SCHEMA_VERSION,
)
from opendoc.properties import (
    ImageProperties as ImageProperties,
)
from opendoc.properties import (
    ParagraphProperties as ParagraphProperties,
)
from opendoc.properties import (
    SectionProperties as SectionProperties,
)
from opendoc.properties import (
    TableCellProperties as TableCellProperties,
)
from opendoc.properties import (
    TableProperties as TableProperties,
)
from opendoc.properties import (
    TableRowProperties as TableRowProperties,
)
from opendoc.properties import (
    TextStyleProperties as TextStyleProperties,
)
from opendoc.properties import (
    VersionedProperties as VersionedProperties,
)
from opendoc.properties import (
    WrapPoint as WrapPoint,
)
from opendoc.properties import (
    WrapPolygon as WrapPolygon,
)
from opendoc.properties import (
    _optional_bool as _optional_bool,
)
from opendoc.properties import (
    _optional_float as _optional_float,
)
from opendoc.properties import (
    _optional_int as _optional_int,
)
from opendoc.properties import (
    _optional_str as _optional_str,
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
