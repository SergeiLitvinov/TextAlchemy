"""Compatibility imports; document implementation lives in opendoc."""

from opendoc.units import (
    CSS_PIXELS_PER_INCH as CSS_PIXELS_PER_INCH,
)
from opendoc.units import (
    EMU_PER_INCH as EMU_PER_INCH,
)
from opendoc.units import (
    EMU_PER_POINT as EMU_PER_POINT,
)
from opendoc.units import (
    OOXML_ANGLE_PER_DEGREE as OOXML_ANGLE_PER_DEGREE,
)
from opendoc.units import (
    POINTS_PER_INCH as POINTS_PER_INCH,
)
from opendoc.units import (
    CoordinateOrigin as CoordinateOrigin,
)
from opendoc.units import (
    Point2D as Point2D,
)
from opendoc.units import (
    Rect2D as Rect2D,
)
from opendoc.units import (
    canonical_coordinate_contract as canonical_coordinate_contract,
)
from opendoc.units import (
    css_px_to_points as css_px_to_points,
)
from opendoc.units import (
    degrees_to_ooxml_angle as degrees_to_ooxml_angle,
)
from opendoc.units import (
    emu_to_inches as emu_to_inches,
)
from opendoc.units import (
    emu_to_points as emu_to_points,
)
from opendoc.units import (
    inches_to_emu as inches_to_emu,
)
from opendoc.units import (
    ooxml_angle_to_degrees as ooxml_angle_to_degrees,
)
from opendoc.units import (
    points_to_css_px as points_to_css_px,
)
from opendoc.units import (
    points_to_emu as points_to_emu,
)
from opendoc.units import (
    round_half_away as round_half_away,
)
from opendoc.units import (
    transform_point_origin as transform_point_origin,
)
from opendoc.units import (
    transform_rect_origin as transform_rect_origin,
)

__all__ = [
    "CSS_PIXELS_PER_INCH",
    "CoordinateOrigin",
    "EMU_PER_INCH",
    "EMU_PER_POINT",
    "OOXML_ANGLE_PER_DEGREE",
    "POINTS_PER_INCH",
    "Point2D",
    "Rect2D",
    "css_px_to_points",
    "canonical_coordinate_contract",
    "degrees_to_ooxml_angle",
    "emu_to_inches",
    "emu_to_points",
    "inches_to_emu",
    "ooxml_angle_to_degrees",
    "points_to_css_px",
    "points_to_emu",
    "round_half_away",
    "transform_point_origin",
    "transform_rect_origin",
]
