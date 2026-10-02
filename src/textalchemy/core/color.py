"""Compatibility imports; document implementation lives in opendoc."""

from opendoc.color import (
    ColorLike as ColorLike,
)
from opendoc.color import (
    ColorSpace as ColorSpace,
)
from opendoc.color import (
    ColorValue as ColorValue,
)
from opendoc.color import (
    _validate_fraction as _validate_fraction,
)
from opendoc.color import (
    color_to_css as color_to_css,
)

__all__ = ["ColorLike", "ColorSpace", "ColorValue", "color_to_css"]
