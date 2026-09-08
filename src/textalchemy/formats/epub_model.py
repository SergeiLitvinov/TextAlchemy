"""Rich EPUB spine importer with links, media, and a small deterministic CSS cascade."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from textalchemy.core.document_model import (
    DocumentModel,
    Image,
    Length,
    Paragraph,
    Provenance,
    Resource,
    ResourceKind,
    Section,
    TextRun,
    TextStyle,
)

_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_DECLARATION = re.compile(r"([\w-]+)\s*:\s*([^;]+)")
_SIZE = re.compile(r"^([0-9.]+)(pt|px|em|rem|%)$")
_BLOCKS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "figcaption"}


def read_epub_model(path: str | Path) -> DocumentModel:
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    from textalchemy.core.io import check_archive_safety

    check_archive_safety(source)
    book = epub.read_epub(str(source))
    resources, item_names = _resources(book, ebooklib, source)
    titles = _toc_titles(book.toc)
    sections, warnings = [], []
    for idref, linear in book.spine:
        if str(linear).lower() == "no":
            continue
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT or isinstance(item, epub.EpubNav):
            continue
        # ebooklib rebuilds XHTML in get_content() and may drop the original head
        # (including linked stylesheets) after reading an existing package.
        soup = BeautifulSoup(item.content, "html.parser")
        rules = _chapter_rules(book, item, soup, ebooklib)
        blocks = []
        body = soup.body or soup
        for tag in body.find_all(_BLOCKS):
            if tag.find_parent(_BLOCKS):
                continue
            content = _inline_content(tag, rules, item.get_name(), item_names, warnings)
            if content or tag.name in {"p", "li"}:
                properties = {"epub": {"tag": tag.name}}
                if tag.get("id"):
                    properties["anchor_id"] = _anchor_id(item.get_name(), tag["id"])
                if tag.name == "li":
                    properties["list_level"] = len(tag.find_parents(["ul", "ol"])) - 1
                    parent = tag.find_parent(["ul", "ol"])
                    properties["list_kind"] = "ordered" if parent and parent.name == "ol" else "unordered"
                blocks.append(
                    Paragraph(
                        content=content,
                        style_id=f"Heading{tag.name[1:]}" if tag.name.startswith("h") else None,
                        properties=properties,
                        provenance=_provenance(source, item.get_name(), tag.get("id")),
                    )
                )
        sections.append(
            Section(
                blocks=blocks,
                properties={
                    "anchor_id": _anchor_id(item.get_name()),
                    "epub": {
                        "id": idref,
                        "href": item.get_name(),
                        "title": titles.get(posixpath.normpath(item.get_name()))
                        or (blocks[0].plain_text if blocks and blocks[0].style_id else ""),
                    },
                },
                provenance=_provenance(source, item.get_name()),
            )
        )
    metadata = {
        "title": _metadata_first(book, "DC", "title"),
        "language": _metadata_first(book, "DC", "language"),
        "identifier": _metadata_first(book, "DC", "identifier"),
        "engine": "ebooklib+bs4",
        "source_name": source.name,
        "epub": {"spine": [section.properties["epub"]["href"] for section in sections], "warnings": warnings},
    }
    return DocumentModel(sections=sections, resources=resources, metadata=metadata, source_format="epub")


def _resources(book, ebooklib, source):
    resources, names = {}, {}
    for item in book.get_items():
        media_type = item.media_type or "application/octet-stream"
        if item.get_type() == ebooklib.ITEM_IMAGE:
            kind = ResourceKind.VECTOR_IMAGE if media_type == "image/svg+xml" else ResourceKind.RASTER_IMAGE
        elif item.get_type() == ebooklib.ITEM_STYLE:
            kind = ResourceKind.ATTACHMENT
        else:
            continue
        resource_id = f"epub-{item.id}"
        name = posixpath.normpath(item.get_name())
        names[name] = resource_id
        resources[resource_id] = Resource(
            resource_id,
            kind,
            media_type,
            data=item.get_content(),
            filename=posixpath.basename(name),
            properties={"epub": {"href": name, "item_id": item.id}},
            provenance=_provenance(source, name, item.id),
        )
    return resources, names


def _chapter_rules(book, item, soup, ebooklib):
    css = []
    hrefs = [link["href"] for link in soup.find_all("link", href=True)]
    hrefs.extend(link.get("href", "") for link in item.get_links() if "stylesheet" in str(link.get("rel", "")))
    for href in dict.fromkeys(hrefs):
        name = _resolve(item.get_name(), href)
        linked = next((entry for entry in book.get_items() if posixpath.normpath(entry.get_name()) == name), None)
        if linked is not None and linked.get_type() == ebooklib.ITEM_STYLE:
            css.append(linked.get_content().decode("utf-8", errors="replace"))
    css.extend(style.get_text() for style in soup.find_all("style"))
    rules = []
    for order, match in enumerate(_RULE.finditer("\n".join(css))):
        declarations = _declarations(match.group(2))
        for selector in match.group(1).split(","):
            selector = selector.strip()
            if re.fullmatch(r"(?:[a-zA-Z][\w-]*)?(?:\.[\w-]+|#[\w-]+)?", selector):
                rules.append((selector, declarations, order))
    return rules


def _inline_content(root, rules, chapter_name, item_names, warnings):
    from bs4 import NavigableString, Tag

    result = []

    def visit(node, inherited, link=None):
        if isinstance(node, NavigableString):
            value = str(node)
            if value.strip() or value == " ":
                result.append(TextRun(value, _text_style(inherited), link=link))
            return
        if not isinstance(node, Tag):
            return
        style = dict(inherited)
        for _, declarations, _ in sorted(_matching_rules(node, rules), key=lambda value: (value[0], value[2])):
            style.update(declarations)
        style.update(_declarations(node.get("style", "")))
        _semantic_style(node.name, style)
        child_link = _resolve_link(chapter_name, node.get("href")) if node.name == "a" else link
        if node.name == "br":
            result.append(TextRun("\n", _text_style(style), link=child_link))
        elif node.name == "img":
            name = _resolve(chapter_name, node.get("src", ""))
            resource_id = item_names.get(name)
            if resource_id:
                result.append(Image(resource_id, alt_text=node.get("alt", ""), provenance=None))
            else:
                warnings.append(f"missing image: {name}")
                if node.get("alt"):
                    result.append(TextRun(node["alt"], _text_style(style), link=child_link))
        else:
            for child in node.children:
                visit(child, style, child_link)

    visit(root, {})
    return result


def _matching_rules(tag, rules):
    for selector, declarations, order in rules:
        element = selector.split(".", 1)[0].split("#", 1)[0]
        matches = not element or tag.name == element.lower()
        specificity = int(bool(element))
        if "#" in selector:
            matches &= tag.get("id") == selector.split("#", 1)[1]
            specificity += 100
        if "." in selector:
            matches &= selector.split(".", 1)[1] in tag.get("class", [])
            specificity += 10
        if matches:
            yield specificity, declarations, order


def _declarations(value):
    return {name.lower(): content.strip() for name, content in _DECLARATION.findall(value)}


def _semantic_style(name, style):
    if name in {"b", "strong"}:
        style["font-weight"] = "bold"
    elif name in {"i", "em"}:
        style["font-style"] = "italic"
    elif name == "u":
        style["text-decoration"] = "underline"
    elif name == "sup":
        style["vertical-align"] = "super"
    elif name == "sub":
        style["vertical-align"] = "sub"


def _text_style(css):
    size = _css_size(css.get("font-size"))
    decoration = css.get("text-decoration", "")
    return TextStyle(
        font_family=css.get("font-family", "").split(",")[0].strip(" '\"") or None,
        font_size=Length(size) if size is not None else None,
        bold=css.get("font-weight") in {"bold", "600", "700", "800", "900"} or None,
        italic=css.get("font-style") in {"italic", "oblique"} or None,
        underline="underline" in decoration or None,
        superscript=css.get("vertical-align") == "super" or None,
        subscript=css.get("vertical-align") == "sub" or None,
        color=css.get("color"),
        background=css.get("background-color"),
    )


def _css_size(value):
    match = _SIZE.match(value or "")
    if not match:
        return None
    number, unit = float(match.group(1)), match.group(2)
    return number if unit == "pt" else number * 0.75 if unit == "px" else number * 12 if unit in {"em", "rem"} else number * 0.12


def _resolve(chapter, href):
    path = unquote(urlsplit(href).path)
    return posixpath.normpath(posixpath.join(posixpath.dirname(chapter), path))


def _resolve_link(chapter, href):
    if not href or urlsplit(href).scheme:
        return href
    split = urlsplit(href)
    resolved = _resolve(chapter, href) if split.path else posixpath.normpath(chapter)
    return "#" + _anchor_id(resolved, split.fragment)


def _anchor_id(chapter, fragment=""):
    value = posixpath.normpath(chapter) + ("--" + fragment if fragment else "")
    return "epub-" + re.sub(r"[^a-zA-Z0-9_.:-]+", "-", value).strip("-")


def _metadata_first(book, namespace, name):
    values = book.get_metadata(namespace, name)
    return values[0][0] if values else ""


def _toc_titles(items):
    result = {}

    def add(link):
        href = getattr(link, "href", "")
        title = getattr(link, "title", "")
        if href and title:
            result[posixpath.normpath(unquote(urlsplit(href).path))] = title

    def visit(entries):
        for entry in entries:
            if isinstance(entry, tuple):
                link, children = entry
                add(link)
                visit(children)
            else:
                add(entry)

    visit(items)
    return result


def _provenance(source, part, object_id=None):
    return Provenance("epub", str(source), object_id=object_id, package_part="/" + part.lstrip("/"))
