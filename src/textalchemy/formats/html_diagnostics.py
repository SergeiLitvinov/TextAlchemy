"""Resolve source-node diagnostics to stable, JSON-persisted imported blocks."""

from contextlib import contextmanager

from textalchemy.core.document_model import Paragraph


class HtmlDiagnostics:
    def __init__(self):
        self.node = None
        self.pending = []
        self.bindings = {}
        self.locations = {}

    @contextmanager
    def at(self, node):
        previous = self.node
        self.node = node
        try:
            yield
        finally:
            self.node = previous

    def warn(self, feature, message, node=None):
        self.pending.append((feature, message, node if node is not None else self.node))

    def bind(self, block, root, nodes=()):
        location = f"html:block:{len(self.locations) + 1}"
        block.properties.setdefault("html", {})["block_id"] = location
        self.bindings.setdefault(id(root), location)
        images = []
        for node in nodes:
            self.bindings.setdefault(id(node), location)
            if getattr(node, "name", None) == "img":
                src = node.get("src", "")
                images.append({
                    "alt": node.get("alt", ""),
                    "source": "Встроенное изображение" if src.startswith("data:") else src[:240],
                })
        self.locations[location] = {
            "label": f"{'Абзац' if isinstance(block, Paragraph) else 'Таблица'} {len(self.locations) + 1}",
            "text": block.plain_text[:1200] if isinstance(block, Paragraph) else root.get_text(" ", strip=True)[:1200],
            "images": images,
        }

    def resolve(self, node):
        if node is None or node.name in {"[document]", "html", "head", "body", "style"}:
            return "html:document"
        if id(node) in self.bindings:
            return self.bindings[id(node)]
        # Container rules point to their first imported block; inline rules to
        # the block containing their text. Omitted nodes use the nearest owner.
        for child in node.descendants:
            if id(child) in self.bindings:
                return self.bindings[id(child)]
        for parent in node.parents:
            if parent.name in {"[document]", "html", "body"}:
                break
            if id(parent) in self.bindings:
                return self.bindings[id(parent)]
        return "html:document"

    def finish(self):
        warnings, seen = [], set()
        for feature, message, node in self.pending:
            location = self.resolve(node)
            key = feature, message, location
            if key not in seen:
                seen.add(key)
                warnings.append({"feature": feature, "message": message, "location": location})
        referenced = {warning["location"] for warning in warnings}
        locations = {key: value for key, value in self.locations.items() if key in referenced}
        if "html:document" in referenced:
            locations["html:document"] = {
                "label": "Весь документ",
                "text": "Общее предупреждение: оно не относится к отдельному импортированному блоку.",
                "images": [],
            }
        return {"warnings": warnings, "locations": locations, "scope": "static-html-v1"}
