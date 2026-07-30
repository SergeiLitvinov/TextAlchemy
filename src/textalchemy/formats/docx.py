"""DOCX → Text.

Единый ридер DOCX; раньше было две копии (extract/text.py и
organize/extractors/docx.py).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Union

from textalchemy.core.document_model import (
    Block as RichBlock,
)
from textalchemy.core.document_model import (
    Box,
    ConversionMode,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    ImageCrop,
    Length,
    PageSettings,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
)
from textalchemy.core.document_model import (
    Table as RichTable,
)
from textalchemy.core.types import Block, BlockType, DocFormat, Table, Text


def read_docx(path: Union[str, Path], *, include_tables: bool = True) -> Text:
    from docx import Document  # type: ignore[import-not-found]

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    doc = Document(str(p))
    blocks: list[Block] = []
    tables: list[Table] = []
    plain: list[str] = []

    for para in doc.paragraphs:
        t = para.text
        blocks.append(Block(type=BlockType.PARAGRAPH, text=t))
        if t:
            plain.append(t)

    if include_tables:
        for tbl in doc.tables:
            rows = [[cell.text for cell in row.cells] for row in tbl.rows]
            tables.append(Table(rows=rows))
            for row in rows:
                plain.append(" | ".join(row))

    return Text(
        blocks=blocks,
        tables=tables,
        plain="\n".join(plain),
        source_format=DocFormat.DOCX,
        engine="python-docx",
    )


def read_docx_model(
    path: Union[str, Path],
    *,
    mode: ConversionMode = ConversionMode.BALANCED,
) -> DocumentModel:
    """Импортировать DOCX в богатую модель с оформлением и ресурсами."""

    from docx import Document as OpenDocument  # type: ignore[import-not-found]
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    document = OpenDocument(str(source))
    model = DocumentModel(
        mode=mode,
        source_format=DocFormat.DOCX.value,
        metadata=_document_metadata(document, source),
        styles=_document_styles(document),
    )
    _load_auxiliary_resources(document, model)
    document_defaults = _document_defaults(document, model)
    if document_defaults is not None:
        model.styles["__doc_defaults__"] = document_defaults

    section_blocks: list[list[RichBlock]] = [[]]
    for item in document.iter_inner_content():
        if isinstance(item, DocxParagraph):
            section_blocks[-1].append(_paragraph_to_model(item, model))
            if item._p.pPr is not None and item._p.pPr.sectPr is not None:
                section_blocks.append([])
        elif isinstance(item, DocxTable):
            section_blocks[-1].append(_table_to_model(item, model))

    if len(section_blocks) > 1 and not section_blocks[-1]:
        section_blocks.pop()
    for index, blocks in enumerate(section_blocks):
        source_section = document.sections[min(index, len(document.sections) - 1)]
        properties = _section_properties(source_section)
        properties["odd_and_even_pages_header_footer"] = bool(
            document.settings.odd_and_even_pages_header_footer
        )
        model.sections.append(
            Section(
                blocks=blocks,
                page=_page_settings(source_section),
                headers=(
                    []
                    if index > 0 and source_section.header.is_linked_to_previous
                    else _container_blocks(source_section.header, model)
                ),
                footers=(
                    []
                    if index > 0 and source_section.footer.is_linked_to_previous
                    else _container_blocks(source_section.footer, model)
                ),
                first_page_headers=_independent_container_blocks(source_section.first_page_header, model),
                first_page_footers=_independent_container_blocks(source_section.first_page_footer, model),
                even_page_headers=_independent_container_blocks(source_section.even_page_header, model),
                even_page_footers=_independent_container_blocks(source_section.even_page_footer, model),
                properties=properties,
            )
        )
    return model


def _document_styles(document: Any) -> dict[str, TextStyle]:
    from docx.enum.style import WD_STYLE_TYPE

    result: dict[str, TextStyle] = {}
    for style in document.styles:
        if style.type not in {WD_STYLE_TYPE.PARAGRAPH, WD_STYLE_TYPE.CHARACTER}:
            continue
        properties = {
            "style_name": style.name,
            "style_type": style.type.name.lower(),
            "base_style_id": style.base_style.style_id if style.base_style is not None else None,
            "hidden": bool(style.hidden),
            "priority": style.priority,
        }
        if style.type is WD_STYLE_TYPE.PARAGRAPH:
            properties.update(_style_paragraph_properties(style))
            properties.update(_numbering_properties(style.element.pPr))
        result[style.style_id] = _resolved_font_style(style, properties=properties)
    return result


def _document_defaults(document: Any, model: DocumentModel) -> TextStyle | None:
    from docx.oxml.ns import qn
    from lxml import etree

    run_defaults = document.styles.element.xpath("./w:docDefaults/w:rPrDefault/w:rPr")
    paragraph_defaults = document.styles.element.xpath("./w:docDefaults/w:pPrDefault/w:pPr")
    if not run_defaults and not paragraph_defaults:
        return None
    run_properties = run_defaults[0] if run_defaults else None
    fonts = run_properties.find(qn("w:rFonts")) if run_properties is not None else None
    font_theme = None
    font_family = None
    if fonts is not None:
        font_family = fonts.get(qn("w:ascii")) or fonts.get(qn("w:hAnsi"))
        font_theme = fonts.get(qn("w:asciiTheme")) or fonts.get(qn("w:hAnsiTheme"))
        if font_family is None and font_theme:
            font_family = _theme_typeface(model, font_theme)
    size = run_properties.find(qn("w:sz")) if run_properties is not None else None
    color = run_properties.find(qn("w:color")) if run_properties is not None else None
    color_value = color.get(qn("w:val")) if color is not None else None
    color_theme = color.get(qn("w:themeColor")) if color is not None else None
    if (not color_value or color_value.lower() == "auto") and color_theme:
        color_value = _theme_color(model, color_theme)
    vertical = run_properties.find(qn("w:vertAlign")) if run_properties is not None else None
    vertical_value = vertical.get(qn("w:val")) if vertical is not None else None
    language = run_properties.find(qn("w:lang")) if run_properties is not None else None
    return TextStyle(
        font_family=font_family,
        font_size=Length(int(size.get(qn("w:val"))) / 2) if size is not None and size.get(qn("w:val")) else None,
        bold=_xml_bool(run_properties, "b"),
        italic=_xml_bool(run_properties, "i"),
        underline=_xml_underline(run_properties),
        superscript=True if vertical_value == "superscript" else None,
        subscript=True if vertical_value == "subscript" else None,
        color=f"#{color_value}" if color_value and color_value.lower() != "auto" else None,
        language=language.get(qn("w:val")) if language is not None else None,
        properties={
            "style_name": "Document Defaults",
            "style_type": "document-default",
            "font_theme": font_theme,
            "color_theme": color_theme,
            "paragraph_defaults_xml": (
                etree.tostring(paragraph_defaults[0], encoding="unicode") if paragraph_defaults else None
            ),
        },
    )


def _theme_typeface(model: DocumentModel, theme_key: str) -> str | None:
    from lxml import etree

    theme = model.resources.get("docx-theme")
    if theme is None:
        return None
    root = etree.fromstring(theme.data or Path(theme.source).read_bytes())
    family = "majorFont" if theme_key.startswith("major") else "minorFont"
    script = "ea" if theme_key.endswith("EastAsia") else "cs" if theme_key.endswith("Bidi") else "latin"
    nodes = root.xpath(
        f"./a:themeElements/a:fontScheme/a:{family}/a:{script}",
        namespaces={"a": "http://schemas.openxmlformats.org/drawingml/2006/main"},
    )
    if not nodes:
        return None
    return nodes[0].get("typeface") or None


def _theme_color(model: DocumentModel, color_key: str) -> str | None:
    from lxml import etree

    theme = model.resources.get("docx-theme")
    if theme is None:
        return None
    root = etree.fromstring(theme.data or Path(theme.source).read_bytes())
    aliases = {"text1": "dk1", "text2": "dk2", "background1": "lt1", "background2": "lt2"}
    key = aliases.get(color_key, color_key)
    nodes = root.xpath(
        f"./a:themeElements/a:clrScheme/a:{key}/*",
        namespaces={"a": "http://schemas.openxmlformats.org/drawingml/2006/main"},
    )
    if not nodes:
        return None
    return nodes[0].get("val") or nodes[0].get("lastClr")


def _xml_bool(parent: Any, local_name: str) -> bool | None:
    from docx.oxml.ns import qn

    if parent is None:
        return None
    node = parent.find(qn(f"w:{local_name}"))
    if node is None:
        return None
    return str(node.get(qn("w:val"), "1")).lower() not in {"0", "false", "off", "none"}


def _xml_underline(parent: Any) -> bool | None:
    from docx.oxml.ns import qn

    if parent is None:
        return None
    node = parent.find(qn("w:u"))
    if node is None:
        return None
    return str(node.get(qn("w:val"), "single")).lower() not in {"0", "false", "off", "none"}


def _load_auxiliary_resources(document: Any, model: DocumentModel) -> None:
    supported = {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes": (
            "docx-footnotes",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
            "footnotes.xml",
        ),
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes": (
            "docx-endnotes",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml",
            "endnotes.xml",
        ),
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering": (
            "docx-numbering",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml",
            "numbering.xml",
        ),
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles": (
            "docx-styles",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
            "styles.xml",
        ),
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme": (
            "docx-theme",
            "application/vnd.openxmlformats-officedocument.theme+xml",
            "theme1.xml",
        ),
    }
    for relationship in document.part.rels.values():
        definition = supported.get(relationship.reltype)
        if definition is None or relationship.is_external:
            continue
        resource_id, media_type, filename = definition
        if resource_id == "docx-numbering" and not _document_uses_numbering(document):
            continue
        target_part = relationship.target_part
        data = target_part.blob
        properties: dict[str, Any] = {
            "role": resource_id,
            "partname": str(target_part.partname),
        }
        if resource_id in {"docx-footnotes", "docx-endnotes"}:
            properties["relationships"] = _load_related_part_resources(target_part, resource_id, model)
        model.add_resource(
            Resource(
                id=resource_id,
                kind=ResourceKind.ATTACHMENT,
                media_type=media_type,
                data=data,
                filename=filename,
                properties=properties,
            )
        )


def _load_related_part_resources(part: Any, owner_resource_id: str, model: DocumentModel) -> list[dict[str, Any]]:
    relationships: list[dict[str, Any]] = []
    for relationship in part.rels.values():
        item: dict[str, Any] = {
            "id": relationship.rId,
            "type": relationship.reltype,
            "external": relationship.is_external,
        }
        if relationship.is_external:
            item["target"] = relationship.target_ref
        else:
            target_part = relationship.target_part
            related_resource_id = f"{owner_resource_id}-{relationship.rId}"
            suffix = Path(str(target_part.partname)).suffix
            media_type = target_part.content_type
            kind = ResourceKind.RASTER_IMAGE if media_type.startswith("image/") else ResourceKind.ATTACHMENT
            model.add_resource(
                Resource(
                    id=related_resource_id,
                    kind=kind,
                    media_type=media_type,
                    data=target_part.blob,
                    filename=Path(str(target_part.partname)).name,
                    properties={
                        "role": "docx-related-part",
                        "owner_resource_id": owner_resource_id,
                        "partname": str(target_part.partname),
                        "suffix": suffix,
                    },
                )
            )
            item["resource_id"] = related_resource_id
        relationships.append(item)
    return relationships


def _document_uses_numbering(document: Any) -> bool:
    from docx.oxml.ns import qn

    if document.element.xpath(".//w:pPr/w:numPr"):
        return True
    used_style_ids = {
        node.get(qn("w:val"))
        for node in document.element.xpath(".//w:pPr/w:pStyle")
        if node.get(qn("w:val"))
    }
    return any(
        style.style_id in used_style_ids and bool(style.element.xpath("./w:pPr/w:numPr"))
        for style in document.styles
    )


def _document_metadata(document: Any, source: Path) -> dict[str, Any]:
    props = document.core_properties
    return {
        "title": props.title or "",
        "subject": props.subject or "",
        "author": props.author or "",
        "keywords": props.keywords or "",
        "comments": props.comments or "",
        "created": props.created.isoformat() if props.created else None,
        "modified": props.modified.isoformat() if props.modified else None,
        "source_name": source.name,
    }


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


def _independent_container_blocks(container: Any, model: DocumentModel) -> list[RichBlock]:
    return [] if container.is_linked_to_previous else _container_blocks(container, model)


def _container_blocks(container: Any, model: DocumentModel) -> list[RichBlock]:
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    result: list[RichBlock] = []
    for item in container.iter_inner_content():
        if isinstance(item, DocxParagraph):
            result.append(_paragraph_to_model(item, model))
        elif isinstance(item, DocxTable):
            result.append(_table_to_model(item, model))
    return result


def _paragraph_to_model(paragraph: Any, model: DocumentModel) -> Paragraph:
    from docx.oxml.ns import qn
    from docx.text.hyperlink import Hyperlink
    from docx.text.run import Run
    from lxml import etree

    content: list[TextRun | Formula | Image] = []
    children = list(paragraph._p.iterchildren())
    index = 0
    while index < len(children):
        child = children[index]
        local_name = etree.QName(child).localname
        if local_name == "r":
            field = _complex_field(children, index, paragraph)
            if field is not None:
                field_run, index = field
                content.append(field_run)
                continue
            _append_run_content(content, Run(child, paragraph), paragraph, model)
        elif local_name == "hyperlink":
            hyperlink = Hyperlink(child, paragraph)
            anchor = child.get(qn("w:anchor"))
            for run in hyperlink.runs:
                _append_run_content(
                    content,
                    run,
                    paragraph,
                    model,
                    link=hyperlink.url or None,
                    anchor=anchor,
                )
        elif local_name == "bookmarkStart":
            content.append(
                TextRun(
                    "",
                    properties={
                        "bookmark_start": {
                            "id": child.get(qn("w:id")),
                            "name": child.get(qn("w:name")),
                        }
                    },
                )
            )
        elif local_name == "bookmarkEnd":
            content.append(TextRun("", properties={"bookmark_end_id": child.get(qn("w:id"))}))
        elif local_name in {"oMath", "oMathPara"}:
            xml = etree.tostring(child, encoding="unicode")
            content.append(
                Formula(
                    value=xml,
                    format=FormulaFormat.OMML,
                    display=local_name == "oMathPara",
                    fallback_text="".join(child.itertext()),
                )
            )
        elif local_name == "fldSimple":
            instruction = child.get(qn("w:instr"), "")
            content.append(
                TextRun(
                    "".join(child.itertext()),
                    properties={
                        "field_instruction": instruction.strip(),
                        "field_xml": [etree.tostring(child, encoding="unicode")],
                    },
                )
            )
        index += 1

    alignment = paragraph.alignment
    alignment_name = alignment.name.lower() if alignment is not None else None
    style_id = paragraph.style.style_id if paragraph.style is not None else None
    properties = _resolved_paragraph_properties(paragraph)
    properties.update(_resolved_numbering_properties(paragraph))
    if paragraph.style is not None:
        properties["style_name"] = paragraph.style.name
    return Paragraph(content=content, style_id=style_id, alignment=alignment_name, properties=properties)


def _append_run_content(
    content: list[TextRun | Formula | Image],
    run: Any,
    paragraph: Any,
    model: DocumentModel,
    *,
    link: str | None = None,
    anchor: str | None = None,
) -> None:
    from docx.oxml.ns import qn

    if run.text:
        properties = {"hyperlink_anchor": anchor} if anchor else {}
        content.append(TextRun(run.text, style=_run_style(run, paragraph), link=link, properties=properties))
    for reference in run._r.xpath(".//w:footnoteReference"):
        content.append(
            TextRun(
                "",
                style=_run_style(run, paragraph),
                properties={
                    "footnote_reference_id": reference.get(qn("w:id")),
                    "resource_id": "docx-footnotes",
                },
            )
        )
    for reference in run._r.xpath(".//w:endnoteReference"):
        content.append(
            TextRun(
                "",
                style=_run_style(run, paragraph),
                properties={
                    "endnote_reference_id": reference.get(qn("w:id")),
                    "resource_id": "docx-endnotes",
                },
            )
        )
    content.extend(_run_images(run, model))


def _complex_field(children: list[Any], start: int, paragraph: Any) -> tuple[TextRun, int] | None:
    from docx.oxml.ns import qn
    from docx.text.run import Run
    from lxml import etree

    first_field_char = children[start].xpath("./w:fldChar")
    if not first_field_char or first_field_char[0].get(qn("w:fldCharType")) != "begin":
        return None
    depth = 0
    separated = False
    instruction_parts: list[str] = []
    result_parts: list[str] = []
    raw_xml: list[str] = []
    result_style = _run_style(Run(children[start], paragraph), paragraph)
    index = start
    while index < len(children):
        child = children[index]
        raw_xml.append(etree.tostring(child, encoding="unicode"))
        for field_char in child.xpath(".//w:fldChar"):
            field_type = field_char.get(qn("w:fldCharType"))
            if field_type == "begin":
                depth += 1
            elif field_type == "separate" and depth == 1:
                separated = True
            elif field_type == "end":
                depth -= 1
        if not separated:
            instruction_parts.extend(node.text or "" for node in child.xpath(".//w:instrText"))
        elif depth > 0:
            texts = child.xpath(".//w:t")
            if texts and not result_parts:
                result_style = _run_style(Run(child, paragraph), paragraph)
            result_parts.extend(node.text or "" for node in texts)
        index += 1
        if depth == 0:
            return (
                TextRun(
                    "".join(result_parts),
                    style=result_style,
                    properties={
                        "field_instruction": "".join(instruction_parts).strip(),
                        "field_complex": True,
                        "field_xml": raw_xml,
                    },
                ),
                index,
            )
    return None


def _run_style(run: Any, paragraph: Any) -> TextStyle:
    sources = [run.font]
    sources.extend(style.font for style in _style_chain(run.style))
    sources.extend(style.font for style in _style_chain(paragraph.style))
    direct_fields = [
        name
        for name in (
            "font_family",
            "font_size",
            "bold",
            "italic",
            "underline",
            "superscript",
            "subscript",
            "color",
            "language",
        )
        if _direct_run_value(run, name) is not None
    ]
    return TextStyle(
        font_family=_first_font_value(sources, "name"),
        font_size=_font_size(_first_font_value(sources, "size")),
        bold=_first_font_value(sources, "bold"),
        italic=_first_font_value(sources, "italic"),
        underline=_underline(_first_font_value(sources, "underline")),
        superscript=_first_font_value(sources, "superscript"),
        subscript=_first_font_value(sources, "subscript"),
        color=_font_color(sources),
        language=_resolved_run_language(run, paragraph),
        properties={
            "style_id": run.style.style_id if run.style is not None else None,
            "style_name": run.style.name if run.style is not None else None,
            "direct_fields": direct_fields,
        },
    )


def _resolved_font_style(style: Any, *, properties: dict[str, Any]) -> TextStyle:
    sources = [item.font for item in _style_chain(style)]
    return TextStyle(
        font_family=_first_font_value(sources, "name"),
        font_size=_font_size(_first_font_value(sources, "size")),
        bold=_first_font_value(sources, "bold"),
        italic=_first_font_value(sources, "italic"),
        underline=_underline(_first_font_value(sources, "underline")),
        superscript=_first_font_value(sources, "superscript"),
        subscript=_first_font_value(sources, "subscript"),
        color=_font_color(sources),
        language=_style_language(style),
        properties=properties,
    )


def _style_chain(style: Any) -> list[Any]:
    result = []
    seen: set[str] = set()
    current = style
    while current is not None and current.style_id not in seen:
        seen.add(current.style_id)
        result.append(current)
        current = current.base_style
    return result


def _first_font_value(sources: list[Any], name: str) -> Any:
    for font in sources:
        value = getattr(font, name)
        if value is not None:
            return value
    return None


def _font_size(value: Any) -> Length | None:
    return Length(float(value.pt)) if value is not None else None


def _underline(value: Any) -> bool | None:
    return bool(value) if value is not None else None


def _font_color(sources: list[Any]) -> str | None:
    for font in sources:
        if font.color is not None and font.color.rgb is not None:
            return f"#{font.color.rgb}"
    return None


def _direct_run_value(run: Any, name: str) -> Any:
    if name == "font_family":
        return run.font.name
    if name == "font_size":
        return run.font.size
    if name == "color":
        return _font_color([run.font])
    if name == "language":
        return _run_language(run)
    return getattr(run.font, name)


def _resolved_run_language(run: Any, paragraph: Any) -> str | None:
    direct = _run_language(run)
    if direct:
        return direct
    for style in [*_style_chain(run.style), *_style_chain(paragraph.style)]:
        language = _style_language(style)
        if language:
            return language
    return None


def _run_language(run: Any) -> str | None:
    from docx.oxml.ns import qn

    language = run._r.xpath("./w:rPr/w:lang")
    if not language:
        return None
    return language[0].get(qn("w:val"))


def _style_language(style: Any) -> str | None:
    from docx.oxml.ns import qn

    for item in _style_chain(style):
        language = item.element.xpath("./w:rPr/w:lang")
        if language:
            return language[0].get(qn("w:val"))
    return None


def _style_paragraph_properties(style: Any) -> dict[str, Any]:
    formats = [item.paragraph_format for item in _style_chain(style)]
    return _resolved_paragraph_values(formats)


def _resolved_paragraph_properties(paragraph: Any) -> dict[str, Any]:
    formats = [paragraph.paragraph_format]
    formats.extend(style.paragraph_format for style in _style_chain(paragraph.style))
    return _resolved_paragraph_values(formats)


def _resolved_paragraph_values(formats: list[Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for name in ("left_indent", "right_indent", "first_line_indent", "space_before", "space_after", "line_spacing"):
        value = next((getattr(item, name) for item in formats if getattr(item, name) is not None), None)
        if hasattr(value, "pt"):
            properties[f"{name}_pt"] = float(value.pt)
        elif value is not None:
            properties[name] = float(value)
    for name in ("keep_together", "keep_with_next", "page_break_before", "widow_control"):
        value = next((getattr(item, name) for item in formats if getattr(item, name) is not None), None)
        if value is not None:
            properties[name] = bool(value)
    return properties


def _resolved_numbering_properties(paragraph: Any) -> dict[str, Any]:
    properties = _numbering_properties(paragraph._p.pPr)
    if properties:
        properties["numbering_source"] = "direct"
        return properties
    for style in _style_chain(paragraph.style):
        properties = _numbering_properties(style.element.pPr)
        if properties:
            properties["numbering_source"] = "style"
            properties["numbering_source_style_id"] = style.style_id
            return properties
    return {}


def _numbering_properties(paragraph_properties: Any) -> dict[str, Any]:
    from docx.oxml.ns import qn

    if paragraph_properties is None:
        return {}
    number_properties = paragraph_properties.find(qn("w:numPr"))
    if number_properties is None:
        return {}
    number_id = number_properties.find(qn("w:numId"))
    level = number_properties.find(qn("w:ilvl"))
    result: dict[str, Any] = {}
    if number_id is not None and number_id.get(qn("w:val")) is not None:
        result["numbering_id"] = int(number_id.get(qn("w:val")))
    if level is not None and level.get(qn("w:val")) is not None:
        result["numbering_level"] = int(level.get(qn("w:val")))
    return result


def _run_images(run: Any, model: DocumentModel) -> list[Image]:
    from docx.oxml.ns import qn
    from lxml import etree

    images: list[Image] = []
    for blip in run._r.xpath(".//a:blip"):
        relationship_id = blip.get(qn("r:embed"))
        if not relationship_id:
            continue
        image_part = run.part.related_parts.get(relationship_id)
        if image_part is None or not hasattr(image_part, "blob"):
            continue
        data = image_part.blob
        digest = hashlib.sha256(data).hexdigest()
        resource_id = f"image-{digest[:16]}"
        if resource_id not in model.resources:
            content_type = image_part.content_type
            vector_types = {"image/svg+xml", "image/x-emf", "image/x-wmf"}
            kind = ResourceKind.VECTOR_IMAGE if content_type in vector_types else ResourceKind.RASTER_IMAGE
            model.add_resource(
                Resource(
                    id=resource_id,
                    kind=kind,
                    media_type=content_type,
                    data=data,
                    filename=Path(str(image_part.partname)).name,
                    properties={"sha256": digest},
                )
            )
        drawing = next(
            (
                ancestor
                for ancestor in blip.iterancestors()
                if etree.QName(ancestor).localname in {"inline", "anchor"}
            ),
            None,
        )
        extent = drawing.xpath("./wp:extent") if drawing is not None else []
        box = None
        if extent:
            x, y = _drawing_position(drawing)
            box = Box(x, y, float(extent[0].get("cx", 0)) / 12700, float(extent[0].get("cy", 0)) / 12700)
        doc_properties = drawing.xpath("./wp:docPr") if drawing is not None else []
        alt_text = ""
        properties = _drawing_properties(drawing)
        crop = _drawing_crop(blip)
        rotation = _drawing_rotation(blip)
        if box is not None:
            box.rotation = rotation
        if doc_properties:
            alt_text = doc_properties[0].get("descr") or doc_properties[0].get("title") or ""
            properties["name"] = doc_properties[0].get("name")
        images.append(Image(resource_id=resource_id, alt_text=alt_text, box=box, properties=properties, crop=crop))
    return images


def _drawing_position(drawing: Any) -> tuple[float, float]:
    if drawing is None:
        return 0.0, 0.0

    def offset(axis: str) -> float:
        values = drawing.xpath(f"./wp:position{axis}/wp:posOffset")
        return float(values[0].text or 0) / 12700 if values else 0.0

    return offset("H"), offset("V")


def _drawing_properties(drawing: Any) -> dict[str, Any]:
    from lxml import etree

    if drawing is None:
        return {}
    placement = etree.QName(drawing).localname
    properties: dict[str, Any] = {"placement": placement}
    if placement != "anchor":
        return properties
    for axis in ("H", "V"):
        positions = drawing.xpath(f"./wp:position{axis}")
        if not positions:
            continue
        position = positions[0]
        prefix = "horizontal" if axis == "H" else "vertical"
        properties[f"{prefix}_relative_from"] = position.get("relativeFrom")
        align = next((child for child in position if etree.QName(child).localname == "align"), None)
        if align is not None:
            properties[f"{prefix}_align"] = align.text
    wrap_element = next(
        (child for child in drawing if etree.QName(child).localname.startswith("wrap")),
        None,
    )
    if wrap_element is not None:
        properties["wrap"] = etree.QName(wrap_element).localname.removeprefix("wrap").lower()
        if wrap_element.get("wrapText") is not None:
            properties["wrap_text"] = wrap_element.get("wrapText")
        polygon = next(
            (child for child in wrap_element if etree.QName(child).localname == "wrapPolygon"),
            None,
        )
        if polygon is not None:
            points = [
                {"x": int(point.get("x", "0")), "y": int(point.get("y", "0"))}
                for point in polygon
                if etree.QName(point).localname in {"start", "lineTo"}
            ]
            properties["wrap_polygon"] = {
                "edited": polygon.get("edited", "0") in {"1", "true", "on"},
                "points": points,
            }
    for source_name, target_name in (
        ("behindDoc", "behind_doc"),
        ("layoutInCell", "layout_in_cell"),
        ("allowOverlap", "allow_overlap"),
        ("relativeHeight", "relative_height"),
    ):
        value = drawing.get(source_name)
        if value is not None:
            properties[target_name] = int(value) if value.isdigit() else value
    return properties


def _drawing_crop(blip: Any) -> ImageCrop | None:
    fill = blip.getparent()
    if fill is None:
        return None
    source_rectangles = fill.xpath("./a:srcRect")
    if not source_rectangles:
        return None
    source = source_rectangles[0]
    return ImageCrop(
        left=int(source.get("l", "0")) / 100000,
        top=int(source.get("t", "0")) / 100000,
        right=int(source.get("r", "0")) / 100000,
        bottom=int(source.get("b", "0")) / 100000,
    )


def _drawing_rotation(blip: Any) -> float:
    pictures = blip.xpath("ancestor::pic:pic[1]")
    if not pictures:
        return 0.0
    transforms = pictures[0].xpath("./pic:spPr/a:xfrm")
    if not transforms or transforms[0].get("rot") is None:
        return 0.0
    return int(transforms[0].get("rot")) / 60000


def _table_to_model(table: Any, model: DocumentModel) -> RichTable:
    from docx.oxml.ns import qn

    rows: list[TableRow] = []
    for row in table.rows:
        cells: list[TableCell] = []
        seen_cells: set[int] = set()
        for cell in row.cells:
            cell_identity = id(cell._tc)
            if cell_identity in seen_cells:
                continue
            seen_cells.add(cell_identity)
            grid_span = cell._tc.xpath("./w:tcPr/w:gridSpan")
            column_span = int(grid_span[0].get(qn("w:val"), "1")) if grid_span else 1
            vertical_merge = cell._tc.xpath("./w:tcPr/w:vMerge")
            properties = _cell_properties(cell)
            if vertical_merge:
                properties["vertical_merge"] = vertical_merge[0].get(qn("w:val"), "continue")
            cells.append(
                TableCell(
                    blocks=_container_blocks(cell, model),
                    column_span=column_span,
                    properties=properties,
                )
            )
        row_properties: dict[str, Any] = {}
        if row._tr.xpath("./w:trPr/w:tblHeader"):
            row_properties["repeat_header"] = True
        rows.append(TableRow(cells=cells, properties=row_properties))
    style_id = table.style.style_id if table.style is not None else None
    properties: dict[str, Any] = {"style_name": table.style.name} if table.style is not None else {}
    properties["autofit"] = bool(table.autofit)
    if table.alignment is not None:
        properties["alignment"] = table.alignment.name.lower()
    grid_widths = [
        int(column.get(qn("w:w")))
        for column in table._tbl.xpath("./w:tblGrid/w:gridCol")
        if column.get(qn("w:w"))
    ]
    if grid_widths:
        properties["grid_widths_twips"] = grid_widths
    return RichTable(rows=rows, style_id=style_id, properties=properties)


def _cell_properties(cell: Any) -> dict[str, Any]:
    from docx.oxml.ns import qn
    from lxml import etree

    properties: dict[str, Any] = {}
    shading = cell._tc.xpath("./w:tcPr/w:shd")
    if shading:
        fill = shading[0].get(qn("w:fill"))
        if fill and fill.lower() != "auto":
            properties["fill"] = fill
    width = cell._tc.xpath("./w:tcPr/w:tcW")
    if width and width[0].get(qn("w:type")) == "dxa":
        properties["width_twips"] = int(width[0].get(qn("w:w"), 0))
    margins = cell._tc.xpath("./w:tcPr/w:tcMar")
    if margins:
        values = {}
        for child in margins[0]:
            value = child.get(qn("w:w"))
            if value is not None:
                values[etree.QName(child).localname] = int(value)
        if values:
            properties["margins_twips"] = values
    if cell.vertical_alignment is not None:
        properties["vertical_alignment"] = cell.vertical_alignment.name.lower()
    return properties


__all__ = ["read_docx", "read_docx_model"]
