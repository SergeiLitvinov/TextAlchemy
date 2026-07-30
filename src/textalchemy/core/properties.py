"""Versioned typed property bags for format-neutral document features."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from typing import Any, ClassVar, TypedDict, cast

PROPERTY_SCHEMA_VERSION = 1


class WrapPoint(TypedDict):
    x: int
    y: int


class WrapPolygon(TypedDict):
    edited: bool
    points: list[WrapPoint]


class VersionedProperties(MutableMapping[str, Any]):
    """Mapping-compatible property bag with a named, versioned schema.

    Unknown keys are deliberately preserved so importers can retain
    format-specific information while stable fields gain typed accessors.
    """

    schema_name: ClassVar[str] = "textalchemy.properties"
    schema_version: ClassVar[int] = PROPERTY_SCHEMA_VERSION

    def __init__(self, values: Mapping[str, Any] | None = None, /, **kwargs: Any) -> None:
        self._values = dict(values or {})
        self._values.update(kwargs)

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._values[key] = value

    def __delitem__(self, key: str) -> None:
        del self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._values!r})"

    def to_dict(self) -> dict[str, Any]:
        return dict(self._values)


class SectionProperties(VersionedProperties):
    schema_name = "textalchemy.section-properties"

    @property
    def start_type(self) -> str | None:
        return _optional_str(self.get("start_type"))

    @property
    def header_linked_to_previous(self) -> bool | None:
        return _optional_bool(self.get("header_linked_to_previous"))

    @property
    def footer_linked_to_previous(self) -> bool | None:
        return _optional_bool(self.get("footer_linked_to_previous"))

    @property
    def first_page_header_linked_to_previous(self) -> bool | None:
        return _optional_bool(self.get("first_page_header_linked_to_previous"))

    @property
    def first_page_footer_linked_to_previous(self) -> bool | None:
        return _optional_bool(self.get("first_page_footer_linked_to_previous"))

    @property
    def even_page_header_linked_to_previous(self) -> bool | None:
        return _optional_bool(self.get("even_page_header_linked_to_previous"))

    @property
    def even_page_footer_linked_to_previous(self) -> bool | None:
        return _optional_bool(self.get("even_page_footer_linked_to_previous"))

    @property
    def different_first_page_header_footer(self) -> bool | None:
        return _optional_bool(self.get("different_first_page_header_footer"))

    @property
    def odd_and_even_pages_header_footer(self) -> bool | None:
        return _optional_bool(self.get("odd_and_even_pages_header_footer"))

    @property
    def header_distance_pt(self) -> float | None:
        return _optional_float(self.get("header_distance_pt"))

    @property
    def footer_distance_pt(self) -> float | None:
        return _optional_float(self.get("footer_distance_pt"))

    @property
    def gutter_pt(self) -> float | None:
        return _optional_float(self.get("gutter_pt"))


class ParagraphProperties(VersionedProperties):
    schema_name = "textalchemy.paragraph-properties"

    @property
    def style_name(self) -> str | None:
        return _optional_str(self.get("style_name"))

    @property
    def left_indent_pt(self) -> float | None:
        return _optional_float(self.get("left_indent_pt"))

    @property
    def right_indent_pt(self) -> float | None:
        return _optional_float(self.get("right_indent_pt"))

    @property
    def first_line_indent_pt(self) -> float | None:
        return _optional_float(self.get("first_line_indent_pt"))

    @property
    def space_before_pt(self) -> float | None:
        return _optional_float(self.get("space_before_pt"))

    @property
    def space_after_pt(self) -> float | None:
        return _optional_float(self.get("space_after_pt"))

    @property
    def line_spacing_pt(self) -> float | None:
        return _optional_float(self.get("line_spacing_pt"))

    @property
    def line_spacing(self) -> float | None:
        return _optional_float(self.get("line_spacing"))

    @property
    def numbering_id(self) -> int | None:
        return _optional_int(self.get("numbering_id"))

    @property
    def numbering_level(self) -> int | None:
        return _optional_int(self.get("numbering_level"))

    @property
    def numbering_source(self) -> str | None:
        return _optional_str(self.get("numbering_source"))

    @property
    def numbering_source_style_id(self) -> str | None:
        return _optional_str(self.get("numbering_source_style_id"))


class TextStyleProperties(ParagraphProperties):
    schema_name = "textalchemy.text-style-properties"

    @property
    def style_type(self) -> str | None:
        return _optional_str(self.get("style_type"))

    @property
    def base_style_id(self) -> str | None:
        return _optional_str(self.get("base_style_id"))

    @property
    def hidden(self) -> bool | None:
        return _optional_bool(self.get("hidden"))

    @property
    def priority(self) -> int | None:
        return _optional_int(self.get("priority"))


class ImageProperties(VersionedProperties):
    schema_name = "textalchemy.image-properties"

    @property
    def placement(self) -> str | None:
        return _optional_str(self.get("placement"))

    @property
    def name(self) -> str | None:
        return _optional_str(self.get("name"))

    @property
    def fallback_resource_id(self) -> str | None:
        return _optional_str(self.get("fallback_resource_id"))

    @property
    def horizontal_relative_from(self) -> str | None:
        return _optional_str(self.get("horizontal_relative_from"))

    @property
    def vertical_relative_from(self) -> str | None:
        return _optional_str(self.get("vertical_relative_from"))

    @property
    def horizontal_align(self) -> str | None:
        return _optional_str(self.get("horizontal_align"))

    @property
    def vertical_align(self) -> str | None:
        return _optional_str(self.get("vertical_align"))

    @property
    def wrap(self) -> str | None:
        return _optional_str(self.get("wrap"))

    @property
    def wrap_text(self) -> str | None:
        return _optional_str(self.get("wrap_text"))

    @property
    def wrap_polygon(self) -> WrapPolygon | None:
        value = self.get("wrap_polygon")
        return cast(WrapPolygon, value) if isinstance(value, dict) else None

    @property
    def behind_doc(self) -> bool | None:
        return _optional_bool(self.get("behind_doc"))

    @property
    def layout_in_cell(self) -> bool | None:
        return _optional_bool(self.get("layout_in_cell"))

    @property
    def allow_overlap(self) -> bool | None:
        return _optional_bool(self.get("allow_overlap"))

    @property
    def relative_height(self) -> int | None:
        return _optional_int(self.get("relative_height"))

    @property
    def flip_horizontal(self) -> bool | None:
        return _optional_bool(self.get("flip_horizontal"))

    @property
    def flip_vertical(self) -> bool | None:
        return _optional_bool(self.get("flip_vertical"))

    @property
    def opacity(self) -> float | None:
        return _optional_float(self.get("opacity"))

    @property
    def grayscale(self) -> bool | None:
        return _optional_bool(self.get("grayscale"))

    @property
    def blip_effects_xml(self) -> list[str]:
        value = self.get("blip_effects_xml")
        return [str(item) for item in value] if isinstance(value, list) else []

    @property
    def line_xml(self) -> str | None:
        return _optional_str(self.get("line_xml"))

    @property
    def shape_effects_xml(self) -> str | None:
        return _optional_str(self.get("shape_effects_xml"))


class TableProperties(VersionedProperties):
    schema_name = "textalchemy.table-properties"

    @property
    def style_name(self) -> str | None:
        return _optional_str(self.get("style_name"))

    @property
    def autofit(self) -> bool | None:
        return _optional_bool(self.get("autofit"))

    @property
    def alignment(self) -> str | None:
        return _optional_str(self.get("alignment"))

    @property
    def grid_widths_twips(self) -> list[int]:
        value = self.get("grid_widths_twips")
        return [int(item) for item in value] if isinstance(value, list) else []


class TableRowProperties(VersionedProperties):
    schema_name = "textalchemy.table-row-properties"

    @property
    def repeat_header(self) -> bool | None:
        return _optional_bool(self.get("repeat_header"))


class TableCellProperties(VersionedProperties):
    schema_name = "textalchemy.table-cell-properties"

    @property
    def fill(self) -> str | None:
        return _optional_str(self.get("fill"))

    @property
    def width_twips(self) -> int | None:
        return _optional_int(self.get("width_twips"))

    @property
    def margins_twips(self) -> dict[str, int]:
        value = self.get("margins_twips")
        if not isinstance(value, dict):
            return {}
        return {str(key): int(item) for key, item in value.items()}

    @property
    def vertical_alignment(self) -> str | None:
        return _optional_str(self.get("vertical_alignment"))

    @property
    def vertical_merge(self) -> str | None:
        return _optional_str(self.get("vertical_merge"))


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "off", "no"}:
            return False
        if normalized in {"1", "true", "on", "yes"}:
            return True
    return bool(value)


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


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
