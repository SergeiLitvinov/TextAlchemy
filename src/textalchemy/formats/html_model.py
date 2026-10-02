"""Static HTML to editable document blocks, without browser or network execution."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from textalchemy.core.document_model import (
    DocumentModel,
    Formula,
    FormulaFormat,
    Paragraph,
    Provenance,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
)
from textalchemy.formats.html_css import Cascade
from textalchemy.formats.html_diagnostics import HtmlDiagnostics
from textalchemy.formats.html_resources import LIMIT, Resources, clean_xml

PARAGRAPHS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "figcaption", "dt", "dd"}
CONTAINERS = {"html", "body", "main", "section", "article", "div", "header", "footer", "nav", "aside", "figure"}
INLINE = {"span", "a", "b", "strong", "i", "em", "u", "sup", "sub", "code", "small", "label", "abbr"}
SKIP = {"head", "style", "script", "link", "meta", "base", "iframe", "object", "embed", "template"}


def read_html_model(path: str | Path, *, resource_root: str | Path | None = None) -> DocumentModel:
    from bs4 import BeautifulSoup

    source = Path(path)
    if source.stat().st_size > LIMIT:
        raise ValueError("HTML exceeds 10 MiB")
    data = source.read_bytes()
    soup = BeautifulSoup(data, "html.parser")
    reader = HtmlReader(soup, source, resource_root)
    for node in soup.find_all(["script", "iframe", "object", "embed", "link", "base"]):
        reader.warn("html-content", f"Не исполнен или не загружен элемент: {node.name}", node)
    for node in soup.find_all(True):
        if any(key.lower().startswith("on") for key in node.attrs):
            reader.warn("html-content", f"Обработчики событий не перенесены: {node.name}", node)
        if node.name == "img" and any(key in node.attrs for key in ("srcset", "width", "height")):
            reader.warn("html-resource", "Размеры и адаптивный выбор img не перенесены; используется исходное изображение.", node)
    blocks = reader.blocks(soup.body or soup)
    return DocumentModel(
        sections=[Section(blocks=blocks)],
        resources=reader.resources.items,
        source_format="html",
        metadata={
            "title": soup.title.get_text() if soup.title else "",
            "source_name": source.name,
            "engine": "bs4+tinycss2",
            "html": reader.diagnostics.finish(),
        },
    )


class HtmlReader:
    def __init__(self, soup, source, resource_root):
        self.source, self.list_count = source, 0
        self.diagnostics = HtmlDiagnostics()
        self.warn = self.diagnostics.warn
        self.css = Cascade(soup, self.warn)
        self.resources = Resources(self.warn, resource_root)

    def blocks(self, root):
        from bs4 import Comment, NavigableString, Tag

        result, content, content_nodes = [], [], []

        def flush():
            has_image = any(getattr(node, "name", None) == "img" for node in content_nodes)
            if not content and not has_image:
                return
            preserve = self.css.style(root).get("white-space") in {"pre", "pre-wrap"}
            visible = [item for item in content if not (isinstance(item, TextRun) and not item.text)]
            if not preserve:
                if visible and isinstance(visible[0], TextRun) and not visible[0].properties.get("html_preserve_space"):
                    visible[0].text = visible[0].text.lstrip(" \t\r\n")
                if visible and isinstance(visible[-1], TextRun) and not visible[-1].properties.get("html_preserve_space"):
                    visible[-1].text = visible[-1].text.rstrip(" \t\r\n")
            has_anchor = any(isinstance(item, TextRun) and item.properties.get("anchor_id") for item in content)
            if has_image or has_anchor or any(not isinstance(item, TextRun) or item.text for item in content):
                css = self.css.style(root)
                props = {"html": {"tag": root.name}}
                if root.get("id") and not result:
                    props["anchor_id"] = root["id"]
                result.append(
                    Paragraph(
                        list(content),
                        style_id=f"Heading{root.name[1]}" if root.name in {"h1", "h2", "h3", "h4", "h5", "h6"} else None,
                        alignment=css.get("text-align"),
                        properties=props,
                        provenance=Provenance("html", str(self.source), object_id=root.get("id")),
                    )
                )
                self.diagnostics.bind(result[-1], root, content_nodes)
            content.clear()
            content_nodes.clear()

        def visit(node):
            with self.diagnostics.at(node.parent if isinstance(node, NavigableString) else node):
                visit_node(node)

        def visit_node(node):
            if isinstance(node, Comment):
                return
            if isinstance(node, NavigableString):
                css = self.css.style(node.parent)
                value = str(node)
                if css.get("white-space") not in {"pre", "pre-wrap"}:
                    value = re.sub(r"[\t\r\n\f ]+", " ", value)
                    previous = next((item for item in reversed(content) if not isinstance(item, TextRun) or item.text), None)
                    if previous is None or (isinstance(previous, TextRun) and previous.text.endswith((" ", "\n"))):
                        value = value.lstrip(" ")
                if value:
                    content_nodes.append(node)
                    anchor = node.find_parent("a")
                    href = self.link(anchor.get("href")) if anchor else None
                    content.append(TextRun(value, self.css.text_style(css, node.parent), link=href,
                                           properties={"html_preserve_space": css.get("white-space") in {"pre", "pre-wrap"}}))
                return
            if not isinstance(node, Tag) or node.name in SKIP:
                return
            if self.css.style(node).get("display") == "none" or node.has_attr("hidden"):
                return
            if node.name in PARAGRAPHS | CONTAINERS:
                flush()
                result.extend(self.blocks(node))
            elif node.name in {"ul", "ol"}:
                flush()
                result.extend(self.list_blocks(node))
            elif node.name == "table":
                flush()
                caption = node.find("caption", recursive=False)
                if caption:
                    result.extend(self.blocks(caption))
                result.append(self.table(node))
            elif node.name == "br":
                content.append(TextRun("\n"))
            elif node.name == "img":
                content_nodes.append(node)
                image = self.resources.image(node.get("src", ""), node.get("alt", ""))
                if image:
                    content.append(image)
                elif node.get("alt"):
                    content.append(TextRun(node["alt"]))
            elif node.name == "svg":
                content_nodes.append(node)
                image = self.resources.svg(str(node), node.get("aria-label", ""))
                if image:
                    content.append(image)
            elif node.name == "math":
                content_nodes.append(node)
                safe = clean_xml(str(node), "math", self.warn)
                if safe:
                    content.append(
                        Formula(safe, FormulaFormat.MATHML, display=node.get("display") == "block", fallback_text=node.get_text())
                    )
            else:
                if node.name not in INLINE:
                    self.warn("html-content", f"Элемент сохранён как содержимое: {node.name}")
                if node.get("id"):
                    content.append(TextRun("", properties={"anchor_id": node["id"]}))
                    content_nodes.append(node)
                for child in node.children:
                    visit(child)

        for child in root.children:
            visit(child)
        flush()
        return result

    def link(self, href):
        if not href:
            return None
        if href.startswith("#") or urlsplit(href).scheme.lower() in {"http", "https", "mailto"}:
            return href
        self.warn("html-links", f"Ссылка не перенесена: {href[:160]}")
        return None

    def list_blocks(self, node):
        self.list_count += 1
        list_id = self.list_count
        depth = len(node.find_parents(["ul", "ol"]))
        try:
            start = int(node.get("start", 1))
        except ValueError:
            start = 1
            self.warn("html-list", "Некорректный start списка заменён единицей.")
        if node.has_attr("reversed") or node.get("type"):
            self.warn("html-list", "Особый тип или обратная нумерация списка не перенесены.")
        result = []
        for index, item in enumerate(node.find_all("li", recursive=False)):
            blocks = self.blocks(item)
            if not blocks or not isinstance(blocks[0], Paragraph) or "html_list_id" in blocks[0].properties:
                blocks.insert(0, Paragraph())
                self.diagnostics.bind(blocks[0], item)
            if any(not isinstance(block, Paragraph) or "html_list_id" not in block.properties for block in blocks[1:]):
                self.warn("html-list", "Многоабзацный пункт списка представлен последовательностью блоков.", item)
            blocks[0].properties.update(
                {
                    "html_list_id": list_id,
                    "list_level": depth,
                    "list_kind": "ordered" if node.name == "ol" else "unordered",
                    "list_start": start,
                    "list_value": start + index,
                }
            )
            if item.get("value"):
                self.warn("html-list", "Индивидуальный номер li не перенесён.", item)
            result.extend(blocks)
        return result

    def table(self, node):
        rows = []
        for row in node.find_all("tr"):
            if row.find_parent("table") is not node:
                continue
            cells = []
            for cell in row.find_all(["td", "th"], recursive=False):
                spans = []
                for key in ("rowspan", "colspan"):
                    try:
                        span = int(cell.get(key, 1))
                        if not 1 <= span <= 100:
                            raise ValueError
                    except ValueError:
                        span = 1
                        self.warn("html-table", f"Некорректное {key} заменено единицей.", cell)
                    spans.append(span)
                cells.append(TableCell(self.blocks(cell), row_span=spans[0], column_span=spans[1]))
            rows.append(TableRow(cells))
        table = Table(rows, properties={"anchor_id": node["id"]} if node.get("id") else {})
        self.diagnostics.bind(table, node)
        return table
