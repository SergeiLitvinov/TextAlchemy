"""Экспорт богатой промежуточной модели в редактируемый DOCX."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import (
    Block,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    Paragraph,
    Resource,
    Section,
    Table,
    TextRun,
    TextStyle,
)


def write_docx_model(document: DocumentModel, output_path: str | Path) -> ConversionReport:
    """Записать ``DocumentModel`` в DOCX и вернуть отчёт о потерях."""

    from docx import Document
    from docx.enum.section import WD_SECTION

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = ConversionReport(output)
    target = Document()
    _write_metadata(target, document.metadata)
    _write_styles(target, document.styles, report)
    _write_auxiliary_parts(target, document, report)
    target.settings.odd_and_even_pages_header_footer = any(
        bool(section.properties.get("odd_and_even_pages_header_footer"))
        or bool(section.even_page_headers)
        or bool(section.even_page_footers)
        for section in document.sections
    )

    sections = document.sections or [Section()]
    counters = {"paragraphs": 0, "tables": 0, "images": 0, "formulas": 0}
    for section_index, source_section in enumerate(sections):
        if section_index == 0:
            target_section = target.sections[0]
        else:
            target_section = target.add_section(_section_start_type(source_section, WD_SECTION))
        _apply_page_settings(target_section, source_section)
        _write_header_footer(target_section, source_section, document, report, section_index, counters)
        _write_blocks(target, source_section.blocks, document, report, f"sections[{section_index}]", counters)

    _restore_exact_style_parts(target, document, report)
    try:
        target.save(output)
    except Exception as error:  # noqa: BLE001 - diagnostic boundary must return a report
        report.add(IssueSeverity.ERROR, "docx-write", str(error))
        return report
    report.metrics.update(counters)
    report.metrics["sections"] = len(sections)
    report.metrics["resources"] = len(document.resources)
    return report


def _write_metadata(target: Any, metadata: dict[str, Any]) -> None:
    properties = target.core_properties
    for name in ("title", "subject", "author", "keywords", "comments"):
        value = metadata.get(name)
        if value is not None:
            setattr(properties, name, str(value))


def _write_styles(target: Any, styles: dict[str, TextStyle], report: ConversionReport) -> None:
    from docx.enum.style import WD_STYLE_TYPE

    created: dict[str, Any] = {}
    for style_id, source in styles.items():
        properties = source.properties
        if properties.get("style_type") == "document-default":
            continue
        style_name = properties.get("style_name") or style_id
        style_type_name = str(properties.get("style_type") or "paragraph").upper()
        style_type = getattr(WD_STYLE_TYPE, style_type_name, WD_STYLE_TYPE.PARAGRAPH)
        try:
            style = target.styles[style_name]
            if style.type != style_type:
                report.add(
                    IssueSeverity.WARNING,
                    "style-type",
                    f"style {style_name!r} exists with incompatible type {style.type.name.lower()}",
                )
                continue
        except KeyError:
            style = target.styles.add_style(style_name, style_type)
        created[style_id] = style
        _apply_font_style(style.font, source)
        _apply_style_language(style, source.language)
        if style_type == WD_STYLE_TYPE.PARAGRAPH:
            _apply_paragraph_format(style.paragraph_format, properties)
            _apply_numbering(style.element.get_or_add_pPr(), properties)
        if properties.get("hidden") is not None:
            style.hidden = bool(properties["hidden"])
        if properties.get("priority") is not None:
            style.priority = int(properties["priority"])

    for style_id, source in styles.items():
        style = created.get(style_id)
        base_style = created.get(source.properties.get("base_style_id"))
        if style is not None and base_style is not None and style != base_style:
            style.base_style = base_style


def _write_auxiliary_parts(target: Any, document: DocumentModel, report: ConversionReport) -> None:
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part

    related_parts = {str(part.partname): part for part in target.part.package.parts}
    note_definitions = (
        (
            "docx-footnotes",
            "wordprocessingml.footnotes+xml",
            "/word/footnotes.xml",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes",
        ),
        (
            "docx-endnotes",
            "wordprocessingml.endnotes+xml",
            "/word/endnotes.xml",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes",
        ),
    )
    for role, media_type_suffix, default_partname, relationship_type in note_definitions:
        resource = next(
            (
                candidate
                for candidate in document.resources.values()
                if candidate.properties.get("role") == role or candidate.media_type.endswith(media_type_suffix)
            ),
            None,
        )
        if resource is None:
            continue
        try:
            partname = PackURI(str(resource.properties.get("partname") or default_partname))
            part = Part(partname, resource.media_type, _resource_bytes(resource), target.part.package)
            _restore_part_relationships(part, resource, document, target.part.package, related_parts)
            target.part.relate_to(part, relationship_type)
        except Exception as error:  # noqa: BLE001 - foreign OOXML parts are diagnostic boundaries
            report.add(IssueSeverity.LOSS, role.removeprefix("docx-"), f"{role} part could not be restored: {error}")

    numbering = next(
        (
            resource
            for resource in document.resources.values()
            if resource.properties.get("role") == "docx-numbering"
            or resource.media_type.endswith("wordprocessingml.numbering+xml")
        ),
        None,
    )
    if numbering is not None:
        try:
            numbering_relationship = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
            for relationship_id, relationship in list(target.part.rels.items()):
                if relationship.reltype == numbering_relationship:
                    target.part.drop_rel(relationship_id)
            part = Part(
                PackURI("/word/numbering.xml"),
                numbering.media_type,
                _resource_bytes(numbering),
                target.part.package,
            )
            target.part.relate_to(part, numbering_relationship)
        except Exception as error:  # noqa: BLE001 - foreign OOXML parts are diagnostic boundaries
            report.add(IssueSeverity.LOSS, "numbering", f"numbering part could not be restored: {error}")


def _restore_exact_style_parts(target: Any, document: DocumentModel, report: ConversionReport) -> None:
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part

    definitions = (
        (
            "docx-styles",
            "wordprocessingml.styles+xml",
            "/word/styles.xml",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
        ),
        (
            "docx-theme",
            "officedocument.theme+xml",
            "/word/theme/theme1.xml",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
        ),
    )
    for role, media_type_suffix, default_partname, relationship_type in definitions:
        resource = next(
            (
                candidate
                for candidate in document.resources.values()
                if candidate.properties.get("role") == role or candidate.media_type.lower().endswith(media_type_suffix)
            ),
            None,
        )
        if resource is None:
            continue
        try:
            for relationship_id, relationship in list(target.part.rels.items()):
                if relationship.reltype == relationship_type:
                    target.part.drop_rel(relationship_id)
            partname = PackURI(str(resource.properties.get("partname") or default_partname))
            part = Part(partname, resource.media_type, _resource_bytes(resource), target.part.package)
            target.part.relate_to(part, relationship_type)
        except Exception as error:  # noqa: BLE001 - exact OOXML style parts are a diagnostic boundary
            report.add(IssueSeverity.LOSS, role.removeprefix("docx-"), f"{role} part could not be restored: {error}")


def _restore_part_relationships(
    part: Any,
    owner: Resource,
    document: DocumentModel,
    package: Any,
    related_parts: dict[str, Any],
) -> None:
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part

    for relationship in owner.properties.get("relationships", []):
        relationship_id = str(relationship["id"])
        relationship_type = str(relationship["type"])
        if relationship.get("external"):
            part.rels.add_relationship(
                relationship_type,
                str(relationship["target"]),
                relationship_id,
                is_external=True,
            )
            continue
        related = document.resources[str(relationship["resource_id"])]
        requested_partname = PackURI(str(related.properties.get("partname") or f"/word/media/{related.filename}"))
        target_part = related_parts.get(str(requested_partname))
        if target_part is None:
            target_part = Part(requested_partname, related.media_type, _resource_bytes(related), package)
            related_parts[str(requested_partname)] = target_part
        part.rels.add_relationship(relationship_type, target_part, relationship_id)


def _resource_bytes(resource: Resource) -> bytes:
    if resource.data is not None:
        return resource.data
    if resource.source is None:
        raise ValueError(f"resource {resource.id!r} has no content")
    return Path(resource.source).read_bytes()


def _section_start_type(source: Section, section_enum: Any) -> Any:
    start_type = str(source.properties.get("start_type") or "NEW_PAGE").upper()
    return getattr(section_enum, start_type, section_enum.NEW_PAGE)


def _apply_page_settings(target: Any, source: Section) -> None:
    from docx.shared import Pt

    target.page_width = Pt(source.page.width.pt)
    target.page_height = Pt(source.page.height.pt)
    target.top_margin = Pt(source.page.margin_top.pt)
    target.right_margin = Pt(source.page.margin_right.pt)
    target.bottom_margin = Pt(source.page.margin_bottom.pt)
    target.left_margin = Pt(source.page.margin_left.pt)
    for name in ("header_distance", "footer_distance", "gutter"):
        value = source.properties.get(f"{name}_pt")
        if value is not None:
            setattr(target, name, Pt(float(value)))
    if source.properties.get("different_first_page_header_footer") is not None:
        target.different_first_page_header_footer = bool(source.properties["different_first_page_header_footer"])
    elif source.first_page_headers or source.first_page_footers:
        target.different_first_page_header_footer = True


def _write_header_footer(
    target: Any,
    source: Section,
    document: DocumentModel,
    report: ConversionReport,
    section_index: int,
    counters: dict[str, int],
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
        _write_blocks(
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


def _write_blocks(
    container: Any,
    blocks: list[Block],
    document: DocumentModel,
    report: ConversionReport,
    location: str,
    counters: dict[str, int],
) -> None:
    for index, block in enumerate(blocks):
        block_location = f"{location}.blocks[{index}]"
        if isinstance(block, Paragraph):
            paragraph = _add_paragraph(container, block, document, report, block_location)
            _write_paragraph_content(paragraph, block, document, report, block_location, counters)
            counters["paragraphs"] += 1
        elif isinstance(block, Table):
            _add_table(container, block, document, report, block_location, counters)
            counters["tables"] += 1
        elif isinstance(block, Formula):
            paragraph = container.add_paragraph()
            _write_formula(paragraph, block, report, block_location)
            counters["formulas"] += 1
        elif isinstance(block, Image):
            paragraph = container.add_paragraph()
            _write_image(paragraph, block, document, report, block_location)
            counters["images"] += 1


def _add_paragraph(
    container: Any,
    source: Paragraph,
    document: DocumentModel,
    report: ConversionReport,
    location: str,
) -> Any:
    style = source.properties.get("style_name") or source.style_id
    try:
        paragraph = container.add_paragraph(style=style) if style else container.add_paragraph()
    except KeyError:
        paragraph = container.add_paragraph()
        report.add(IssueSeverity.WARNING, "paragraph-style", f"style {style!r} is unavailable", location)
    if source.alignment:
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        alignment = getattr(WD_ALIGN_PARAGRAPH, source.alignment.upper(), None)
        if alignment is not None:
            paragraph.alignment = alignment
    _apply_paragraph_properties(paragraph, source.properties)
    preserves_style_numbering = (
        source.properties.get("numbering_source") == "style"
        and source.properties.get("numbering_source_style_id") == source.style_id
        and any(resource.properties.get("role") == "docx-styles" for resource in document.resources.values())
    )
    if not preserves_style_numbering:
        _apply_numbering(paragraph._p.get_or_add_pPr(), source.properties)
    return paragraph


def _apply_paragraph_properties(paragraph: Any, properties: dict[str, Any]) -> None:
    _apply_paragraph_format(paragraph.paragraph_format, properties)


def _apply_paragraph_format(paragraph_format: Any, properties: dict[str, Any]) -> None:
    from docx.shared import Pt

    for name in ("left_indent", "right_indent", "first_line_indent", "space_before", "space_after"):
        value = properties.get(f"{name}_pt")
        if value is not None:
            setattr(paragraph_format, name, Pt(value))
    if properties.get("line_spacing_pt") is not None:
        paragraph_format.line_spacing = Pt(properties["line_spacing_pt"])
    if properties.get("line_spacing") is not None:
        paragraph_format.line_spacing = properties["line_spacing"]
    for name in ("keep_together", "keep_with_next", "page_break_before", "widow_control"):
        if properties.get(name) is not None:
            setattr(paragraph_format, name, bool(properties[name]))


def _apply_numbering(paragraph_properties: Any, properties: dict[str, Any]) -> None:
    if properties.get("numbering_id") is None:
        return
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    existing = paragraph_properties.find(qn("w:numPr"))
    if existing is not None:
        paragraph_properties.remove(existing)
    number_properties = OxmlElement("w:numPr")
    if properties.get("numbering_level") is not None:
        level = OxmlElement("w:ilvl")
        level.set(qn("w:val"), str(int(properties["numbering_level"])))
        number_properties.append(level)
    number_id = OxmlElement("w:numId")
    number_id.set(qn("w:val"), str(int(properties["numbering_id"])))
    number_properties.append(number_id)
    paragraph_properties.append(number_properties)


def _write_paragraph_content(
    paragraph: Any,
    source: Paragraph,
    document: DocumentModel,
    report: ConversionReport,
    location: str,
    counters: dict[str, int],
) -> None:
    for index, item in enumerate(source.content):
        item_location = f"{location}.content[{index}]"
        if isinstance(item, TextRun):
            if item.properties.get("bookmark_start") is not None:
                _write_bookmark_start(paragraph, item.properties["bookmark_start"])
            elif item.properties.get("bookmark_end_id") is not None:
                _write_bookmark_end(paragraph, item.properties["bookmark_end_id"])
            elif item.properties.get("footnote_reference_id") is not None:
                _write_footnote_reference(paragraph, item)
            elif item.properties.get("endnote_reference_id") is not None:
                _write_endnote_reference(paragraph, item)
            elif item.properties.get("field_xml"):
                _write_raw_field(paragraph, item.properties["field_xml"])
            elif item.properties.get("field_instruction") is not None:
                _write_simple_field(paragraph, item)
            else:
                run = paragraph.add_run(item.text)
                _apply_text_style(run, item.style)
                if item.link:
                    _wrap_hyperlink(paragraph, run, item.link)
                elif item.properties.get("hyperlink_anchor"):
                    _wrap_internal_hyperlink(paragraph, run, str(item.properties["hyperlink_anchor"]))
        elif isinstance(item, Formula):
            _write_formula(paragraph, item, report, item_location)
            counters["formulas"] += 1
        elif isinstance(item, Image):
            _write_image(paragraph, item, document, report, item_location)
            counters["images"] += 1


def _apply_text_style(run: Any, style: TextStyle) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    _apply_font_style(run.font, style)
    if style.language:
        run_properties = run._r.get_or_add_rPr()
        language = OxmlElement("w:lang")
        language.set(qn("w:val"), style.language)
        run_properties.append(language)


def _apply_font_style(font: Any, style: TextStyle) -> None:
    from docx.shared import Pt, RGBColor

    if style.font_family:
        font.name = style.font_family
    if style.font_size:
        font.size = Pt(style.font_size.pt)
    font.bold = style.bold
    font.italic = style.italic
    font.underline = style.underline
    font.superscript = style.superscript
    font.subscript = style.subscript
    if style.color:
        color = style.color.removeprefix("#")
        if len(color) == 6:
            font.color.rgb = RGBColor.from_string(color)


def _apply_style_language(style: Any, language_code: str | None) -> None:
    if not language_code:
        return
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run_properties = style.element.get_or_add_rPr()
    language = OxmlElement("w:lang")
    language.set(qn("w:val"), language_code)
    run_properties.append(language)


def _wrap_hyperlink(paragraph: Any, run: Any, url: str) -> None:
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    relationship_id = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)
    run._r.getparent().remove(run._r)
    hyperlink.append(run._r)
    paragraph._p.append(hyperlink)


def _wrap_internal_hyperlink(paragraph: Any, run: Any, anchor: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("w:anchor"), anchor)
    run._r.getparent().remove(run._r)
    hyperlink.append(run._r)
    paragraph._p.append(hyperlink)


def _write_bookmark_start(paragraph: Any, bookmark: dict[str, Any]) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bookmark.get("id") or "0"))
    start.set(qn("w:name"), str(bookmark.get("name") or "_TextAlchemy"))
    paragraph._p.append(start)


def _write_bookmark_end(paragraph: Any, bookmark_id: Any) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bookmark_id))
    paragraph._p.append(end)


def _write_footnote_reference(paragraph: Any, item: TextRun) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = paragraph.add_run()
    _apply_text_style(run, item.style)
    reference = OxmlElement("w:footnoteReference")
    reference.set(qn("w:id"), str(item.properties["footnote_reference_id"]))
    run._r.append(reference)


def _write_endnote_reference(paragraph: Any, item: TextRun) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = paragraph.add_run()
    _apply_text_style(run, item.style)
    reference = OxmlElement("w:endnoteReference")
    reference.set(qn("w:id"), str(item.properties["endnote_reference_id"]))
    run._r.append(reference)


def _write_simple_field(paragraph: Any, item: TextRun) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), str(item.properties["field_instruction"]))
    if item.text:
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = item.text
        run.append(text)
        field.append(run)
    paragraph._p.append(field)


def _write_raw_field(paragraph: Any, raw_elements: list[str]) -> None:
    from docx.oxml import parse_xml

    for raw_xml in raw_elements:
        paragraph._p.append(parse_xml(raw_xml))


def _write_formula(paragraph: Any, formula: Formula, report: ConversionReport, location: str) -> None:
    if formula.format is FormulaFormat.OMML:
        from docx.oxml import parse_xml

        try:
            paragraph._p.append(parse_xml(formula.value))
            return
        except Exception as error:  # noqa: BLE001 - malformed foreign XML is reported as a loss
            report.add(IssueSeverity.LOSS, "formula", f"invalid OMML replaced by fallback: {error}", location)
    else:
        report.add(
            IssueSeverity.LOSS,
            "formula",
            f"{formula.format.value} is not natively convertible to OMML; fallback text used",
            location,
        )
    paragraph.add_run(formula.fallback_text or formula.value)


def _write_image(
    paragraph: Any,
    image: Image,
    document: DocumentModel,
    report: ConversionReport,
    location: str,
) -> None:
    from docx.shared import Pt

    resource = document.resources.get(image.resource_id)
    if resource is None:
        report.add(IssueSeverity.ERROR, "image", f"resource {image.resource_id!r} not found", location)
        paragraph.add_run(image.alt_text)
        return
    if resource.media_type in {"image/svg+xml", "image/x-emf", "image/x-wmf"}:
        try:
            _add_vector_picture(paragraph, image, resource)
            return
        except Exception as error:  # noqa: BLE001 - malformed vector resources must produce a diagnostic
            report.add(
                IssueSeverity.LOSS,
                "image",
                f"{resource.media_type} could not be embedded; alt text used: {error}",
                location,
            )
            paragraph.add_run(image.alt_text or f"[{resource.filename or resource.id}]")
            return
    stream = _resource_stream(resource)
    width = Pt(image.box.width) if image.box and image.box.width > 0 else None
    height = Pt(image.box.height) if image.box and image.box.height > 0 else None
    try:
        shape = paragraph.add_run().add_picture(stream, width=width, height=height)
        if image.alt_text:
            properties = shape._inline.docPr
            properties.set("descr", image.alt_text)
        _apply_image_transform(shape._inline, image)
        _apply_image_placement(shape._inline, image)
    except Exception as error:  # noqa: BLE001 - image backends raise several library-specific errors
        report.add(
            IssueSeverity.LOSS,
            "image",
            f"{resource.media_type} could not be embedded; alt text used: {error}",
            location,
        )
        paragraph.add_run(image.alt_text or f"[{resource.filename or resource.id}]")


def _add_vector_picture(paragraph: Any, image: Image, resource: Resource) -> None:
    """Встроить поддерживаемый Word вектор без декодирования через Pillow."""

    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.opc.part import Part
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    data = resource.data
    if data is None:
        if resource.source is None:
            raise ValueError(f"resource {resource.id!r} has no content")
        data = Path(resource.source).read_bytes()
    extension = {
        "image/svg+xml": "svg",
        "image/x-emf": "emf",
        "image/x-wmf": "wmf",
    }[resource.media_type]
    package = paragraph.part.package
    partname = package.next_partname(f"/word/media/vector%d.{extension}")
    vector_part = Part(partname, resource.media_type, data, package)
    relationship_id = paragraph.part.relate_to(vector_part, RELATIONSHIP_TYPE.IMAGE)
    width_pt = image.box.width if image.box and image.box.width > 0 else 288.0
    height_pt = image.box.height if image.box and image.box.height > 0 else 144.0
    width_emu = round(width_pt * 12700)
    height_emu = round(height_pt * 12700)
    drawing_id = paragraph.part.next_id
    xml = (
        f'<w:r {nsdecls("w", "wp", "a", "pic", "r")}><w:drawing>'
        '<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{width_emu}" cy="{height_emu}"/>'
        f'<wp:docPr id="{drawing_id}" name="Vector {drawing_id}"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic><pic:nvPicPr>'
        f'<pic:cNvPr id="0" name="vector.{extension}"/><pic:cNvPicPr/>'
        '</pic:nvPicPr><pic:blipFill>'
        f'<a:blip r:embed="{relationship_id}"/><a:stretch><a:fillRect/></a:stretch>'
        '</pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{width_emu}" cy="{height_emu}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        '</pic:spPr></pic:pic></a:graphicData></a:graphic>'
        '</wp:inline></w:drawing></w:r>'
    )
    run = parse_xml(xml)
    if image.alt_text:
        run.xpath(".//wp:docPr")[0].set("descr", image.alt_text)
    inline = run.xpath(".//wp:inline")[0]
    _apply_image_transform(inline, image)
    _apply_image_placement(inline, image)
    paragraph._p.append(run)


def _apply_image_transform(drawing: Any, image: Image) -> None:
    from docx.oxml import OxmlElement

    transforms = drawing.xpath(".//pic:spPr/a:xfrm")
    if transforms and image.box is not None and image.box.rotation:
        transforms[0].set("rot", str(round(image.box.rotation * 60000)))
    if image.crop is None:
        return
    fills = drawing.xpath(".//pic:blipFill")
    if not fills:
        return
    source = OxmlElement("a:srcRect")
    for attribute, value in (
        ("l", image.crop.left),
        ("t", image.crop.top),
        ("r", image.crop.right),
        ("b", image.crop.bottom),
    ):
        if value:
            source.set(attribute, str(round(value * 100000)))
    blips = fills[0].xpath("./a:blip")
    fills[0].insert(fills[0].index(blips[0]) + 1 if blips else 0, source)


def _apply_image_placement(drawing: Any, image: Image) -> None:
    if image.properties.get("placement") != "anchor":
        return
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    drawing.tag = qn("wp:anchor")
    for name, default in (
        ("distT", "0"),
        ("distB", "0"),
        ("distL", "0"),
        ("distR", "0"),
        ("simplePos", "0"),
        ("relativeHeight", str(image.properties.get("relative_height", 0))),
        ("behindDoc", str(int(bool(image.properties.get("behind_doc", False))))),
        ("locked", "0"),
        ("layoutInCell", str(int(bool(image.properties.get("layout_in_cell", True))))),
        ("allowOverlap", str(int(bool(image.properties.get("allow_overlap", True))))),
    ):
        drawing.set(name, default)

    simple_position = OxmlElement("wp:simplePos")
    simple_position.set("x", "0")
    simple_position.set("y", "0")
    drawing.insert(0, simple_position)
    for index, (axis, coordinate) in enumerate((("H", "x"), ("V", "y")), 1):
        prefix = "horizontal" if axis == "H" else "vertical"
        position = OxmlElement(f"wp:position{axis}")
        position.set("relativeFrom", str(image.properties.get(f"{prefix}_relative_from") or "page"))
        alignment = image.properties.get(f"{prefix}_align")
        if alignment:
            node = OxmlElement("wp:align")
            node.text = str(alignment)
        else:
            node = OxmlElement("wp:posOffset")
            value = getattr(image.box, coordinate) if image.box is not None else 0
            node.text = str(round(value * 12700))
        position.append(node)
        drawing.insert(index, position)

    wrap_name = str(image.properties.get("wrap") or "none").lower()
    wrap_tags = {
        "none": "wp:wrapNone",
        "square": "wp:wrapSquare",
        "tight": "wp:wrapTight",
        "through": "wp:wrapThrough",
        "topandbottom": "wp:wrapTopAndBottom",
    }
    wrap = OxmlElement(wrap_tags.get(wrap_name, "wp:wrapNone"))
    if wrap_name in {"square", "tight", "through"}:
        wrap.set("wrapText", str(image.properties.get("wrap_text") or "bothSides"))
    polygon = image.properties.get("wrap_polygon")
    if wrap_name in {"tight", "through"} and isinstance(polygon, dict):
        points = polygon.get("points")
        if isinstance(points, list) and points:
            polygon_element = OxmlElement("wp:wrapPolygon")
            polygon_element.set("edited", str(int(bool(polygon.get("edited", False)))))
            for index, point in enumerate(points):
                if not isinstance(point, dict):
                    continue
                node = OxmlElement("wp:start" if index == 0 else "wp:lineTo")
                node.set("x", str(int(point.get("x", 0))))
                node.set("y", str(int(point.get("y", 0))))
                polygon_element.append(node)
            if len(polygon_element):
                wrap.append(polygon_element)
    doc_properties = drawing.find(qn("wp:docPr"))
    drawing.insert(drawing.index(doc_properties) if doc_properties is not None else 4, wrap)


def _resource_stream(resource: Resource) -> BytesIO | str:
    if resource.data is not None:
        return BytesIO(resource.data)
    if resource.source is None:
        raise ValueError(f"resource {resource.id!r} has no content")
    return resource.source


def _add_table(
    container: Any,
    source: Table,
    document: DocumentModel,
    report: ConversionReport,
    location: str,
    counters: dict[str, int],
) -> None:
    column_count = max((sum(max(cell.column_span, 1) for cell in row.cells) for row in source.rows), default=1)
    row_count = max(len(source.rows), 1)
    try:
        target = container.add_table(rows=row_count, cols=column_count)
    except TypeError:
        from docx.shared import Inches

        target = container.add_table(rows=row_count, cols=column_count, width=Inches(6))
    _apply_table_properties(target, source.properties)
    if source.style_id:
        _set_table_style_id(target, source.style_id)
    elif source.properties.get("style_name"):
        try:
            target.style = source.properties["style_name"]
        except KeyError:
            report.add(
                IssueSeverity.WARNING,
                "table-style",
                f"style {source.properties['style_name']!r} is unavailable",
                location,
            )
    for row_index, source_row in enumerate(source.rows):
        _apply_row_properties(target.rows[row_index], source_row.properties)
        column_index = 0
        for cell_index, source_cell in enumerate(source_row.cells):
            span = max(source_cell.column_span, 1)
            target_cell = target.cell(row_index, column_index)
            if span > 1:
                target_cell = target_cell.merge(target.cell(row_index, min(column_index + span - 1, column_count - 1)))
            _apply_cell_properties(target_cell, source_cell.properties)
            _clear_container(target_cell)
            _write_blocks(
                target_cell,
                source_cell.blocks,
                document,
                report,
                f"{location}.rows[{row_index}].cells[{cell_index}]",
                counters,
            )
            if not source_cell.blocks:
                target_cell.add_paragraph()
            if source_cell.row_span > 1:
                report.add(IssueSeverity.LOSS, "table-row-span", "vertical merge is not yet exported", location)
            column_index += span


def _set_table_style_id(table: Any, style_id: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = table._tbl.tblPr
    style = properties.find(qn("w:tblStyle"))
    if style is None:
        style = OxmlElement("w:tblStyle")
        properties.insert(0, style)
    style.set(qn("w:val"), style_id)


def _apply_table_properties(table: Any, properties: dict[str, Any]) -> None:
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn

    if properties.get("autofit") is not None:
        table.autofit = bool(properties["autofit"])
    if properties.get("alignment"):
        alignment = getattr(WD_TABLE_ALIGNMENT, str(properties["alignment"]).upper(), None)
        if alignment is not None:
            table.alignment = alignment
    grid_widths = properties.get("grid_widths_twips") or []
    columns = table._tbl.xpath("./w:tblGrid/w:gridCol")
    for column, width in zip(columns, grid_widths, strict=False):
        column.set(qn("w:w"), str(int(width)))


def _apply_row_properties(row: Any, properties: dict[str, Any]) -> None:
    if not properties.get("repeat_header"):
        return
    from docx.oxml import OxmlElement

    row._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))


def _apply_cell_properties(cell: Any, properties: dict[str, Any]) -> None:
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    cell_properties = cell._tc.get_or_add_tcPr()
    if properties.get("fill"):
        shading = cell_properties.find(qn("w:shd"))
        if shading is None:
            shading = OxmlElement("w:shd")
            cell_properties.append(shading)
        shading.set(qn("w:fill"), str(properties["fill"]))
    if properties.get("width_twips") is not None:
        width = cell_properties.get_or_add_tcW()
        width.set(qn("w:type"), "dxa")
        width.set(qn("w:w"), str(int(properties["width_twips"])))
    margins = properties.get("margins_twips") or {}
    if margins:
        margin_node = cell_properties.first_child_found_in("w:tcMar")
        if margin_node is None:
            margin_node = OxmlElement("w:tcMar")
            cell_properties.append(margin_node)
        for edge, value in margins.items():
            node = margin_node.find(qn(f"w:{edge}"))
            if node is None:
                node = OxmlElement(f"w:{edge}")
                margin_node.append(node)
            node.set(qn("w:w"), str(int(value)))
            node.set(qn("w:type"), "dxa")
    if properties.get("vertical_alignment"):
        alignment = getattr(WD_CELL_VERTICAL_ALIGNMENT, str(properties["vertical_alignment"]).upper(), None)
        if alignment is not None:
            cell.vertical_alignment = alignment


__all__ = ["write_docx_model"]
