"""DOCX section exporter for page geometry and running content."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textalchemy.core.diagnostics import ConversionReport
from textalchemy.core.document_model import Block, DocumentModel, Section

BlockWriter = Callable[
    [Any, list[Block], DocumentModel, ConversionReport, str, dict[str, int]],
    None,
]


def section_start_type(source: Section, section_enum: Any) -> Any:
    start_type = str(source.properties.start_type or "NEW_PAGE").upper()
    return getattr(section_enum, start_type, section_enum.NEW_PAGE)


def configure_section(
    target: Any,
    source: Section,
    document: DocumentModel,
    report: ConversionReport,
    section_index: int,
    counters: dict[str, int],
    write_blocks: BlockWriter,
) -> None:
    _apply_page_settings(target, source)
    _write_header_footer(target, source, document, report, section_index, counters, write_blocks)


def _apply_page_settings(target: Any, source: Section) -> None:
    from docx.shared import Pt

    target.page_width = Pt(source.page.width.pt)
    target.page_height = Pt(source.page.height.pt)
    target.top_margin = Pt(source.page.margin_top.pt)
    target.right_margin = Pt(source.page.margin_right.pt)
    target.bottom_margin = Pt(source.page.margin_bottom.pt)
    target.left_margin = Pt(source.page.margin_left.pt)
    for name, value in (
        ("header_distance", source.properties.header_distance_pt),
        ("footer_distance", source.properties.footer_distance_pt),
        ("gutter", source.properties.gutter_pt),
    ):
        if value is not None:
            setattr(target, name, Pt(value))
    if source.properties.different_first_page_header_footer is not None:
        target.different_first_page_header_footer = source.properties.different_first_page_header_footer
    elif source.first_page_headers or source.first_page_footers:
        target.different_first_page_header_footer = True


def _write_header_footer(
    target: Any,
    source: Section,
    document: DocumentModel,
    report: ConversionReport,
    section_index: int,
    counters: dict[str, int],
    write_blocks: BlockWriter,
) -> None:
    definitions = (
        (target.header, source.headers, "header_linked_to_previous", "headers"),
        (target.footer, source.footers, "footer_linked_to_previous", "footers"),
        (
            target.first_page_header,
            source.first_page_headers,
            "first_page_header_linked_to_previous",
            "first_page_headers",
        ),
        (
            target.first_page_footer,
            source.first_page_footers,
            "first_page_footer_linked_to_previous",
            "first_page_footers",
        ),
        (
            target.even_page_header,
            source.even_page_headers,
            "even_page_header_linked_to_previous",
            "even_page_headers",
        ),
        (
            target.even_page_footer,
            source.even_page_footers,
            "even_page_footer_linked_to_previous",
            "even_page_footers",
        ),
    )
    for container, blocks, linkage_property, collection_name in definitions:
        if (
            linkage_property not in source.properties
            and not blocks
            and collection_name.startswith(("first_page_", "even_page_"))
        ):
            continue
        linked = bool(source.properties.get(linkage_property))
        container.is_linked_to_previous = linked
        if linked:
            continue
        _clear_container(container)
        write_blocks(
            container,
            blocks,
            document,
            report,
            f"sections[{section_index}].{collection_name}",
            counters,
        )


def _clear_container(container: Any) -> None:
    from lxml import etree

    element = container._element
    for child in list(element):
        if etree.QName(child).localname in {"p", "tbl"}:
            element.remove(child)


__all__ = ["configure_section", "section_start_type"]
