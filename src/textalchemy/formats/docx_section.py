"""DOCX section importer for page geometry and running content."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textalchemy.core.document_model import Block, DocumentModel, Length, PageSettings, Section

BlockReader = Callable[[Any, DocumentModel], list[Block]]


def read_section(
    source: Any,
    blocks: list[Block],
    model: DocumentModel,
    section_index: int,
    read_blocks: BlockReader,
    *,
    odd_and_even_pages: bool,
) -> Section:
    properties = _section_properties(source)
    properties["odd_and_even_pages_header_footer"] = odd_and_even_pages
    return Section(
        blocks=blocks,
        page=_page_settings(source),
        headers=([] if section_index > 0 and source.header.is_linked_to_previous else read_blocks(source.header, model)),
        footers=([] if section_index > 0 and source.footer.is_linked_to_previous else read_blocks(source.footer, model)),
        first_page_headers=_independent_blocks(source.first_page_header, model, read_blocks),
        first_page_footers=_independent_blocks(source.first_page_footer, model, read_blocks),
        even_page_headers=_independent_blocks(source.even_page_header, model, read_blocks),
        even_page_footers=_independent_blocks(source.even_page_footer, model, read_blocks),
        properties=properties,
    )


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


def _section_properties(section: Any) -> dict[str, Any]:
    def points(value: Any) -> float | None:
        return float(value.pt) if value is not None else None

    start_type = section.start_type
    return {
        "start_type": start_type.name if start_type is not None else None,
        "header_linked_to_previous": bool(section.header.is_linked_to_previous),
        "footer_linked_to_previous": bool(section.footer.is_linked_to_previous),
        "first_page_header_linked_to_previous": bool(section.first_page_header.is_linked_to_previous),
        "first_page_footer_linked_to_previous": bool(section.first_page_footer.is_linked_to_previous),
        "even_page_header_linked_to_previous": bool(section.even_page_header.is_linked_to_previous),
        "even_page_footer_linked_to_previous": bool(section.even_page_footer.is_linked_to_previous),
        "header_distance_pt": points(section.header_distance),
        "footer_distance_pt": points(section.footer_distance),
        "gutter_pt": points(section.gutter),
        "different_first_page_header_footer": bool(section.different_first_page_header_footer),
    }


def _independent_blocks(container: Any, model: DocumentModel, read_blocks: BlockReader) -> list[Block]:
    return [] if container.is_linked_to_previous else read_blocks(container, model)


__all__ = ["read_section"]
