"""Embedded HTML resources with explicit opt-in for a bounded local directory."""

from __future__ import annotations

import base64
import binascii
import hashlib
import mimetypes
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urlsplit

from textalchemy.core.document_model import Image, Resource, ResourceKind

LIMIT = 10 * 1024 * 1024
RASTER_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def clean_xml(value, kind, warn):
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", value, re.I):
        warn("html-resource", f"{kind}: DTD/entity не допускаются.")
        return None
    try:
        root = ET.fromstring(value)
    except ET.ParseError:
        warn("html-resource", f"Некорректный XML {kind}.")
        return None
    namespace = "http://www.w3.org/2000/svg" if kind == "svg" else "http://www.w3.org/1998/Math/MathML"
    if root.tag.rsplit("}", 1)[-1].lower() != ("svg" if kind == "svg" else "math"):
        warn("html-resource", f"Некорректный корневой элемент {kind}.")
        return None
    cases = {
        "viewbox": "viewBox",
        "preserveaspectratio": "preserveAspectRatio",
        "lineargradient": "linearGradient",
        "radialgradient": "radialGradient",
        "gradientunits": "gradientUnits",
        "gradienttransform": "gradientTransform",
        "clippath": "clipPath",
        "clippathunits": "clipPathUnits",
    }
    for node in list(root.iter()):
        local = node.tag.rsplit("}", 1)[-1]
        node.tag = "{" + namespace + "}" + cases.get(local.lower(), local)
        for child in list(node):
            name = child.tag.rsplit("}", 1)[-1].lower()
            if name in {"script", "foreignobject", "iframe", "style", "animate", "animatetransform", "set", "annotation-xml"}:
                node.remove(child)
                warn("html-resource", f"Активный или неподдержанный элемент {kind}: {name}")
        for key, value in list(node.attrib.items()):
            local = key.rsplit("}", 1)[-1].lower()
            unsafe = local.startswith("on") or local in {"style", "src"} or (local == "href" and not value.startswith("#"))
            unsafe |= bool(re.search(r"url\(\s*['\"]?(?!#)", value, re.I))
            if unsafe:
                del node.attrib[key]
                warn("html-resource", f"Атрибут {kind} не перенесён: {local}")
            elif local in cases:
                del node.attrib[key]
                node.set(cases[local], value)
    return ET.tostring(root, encoding="unicode")


class Resources:
    def __init__(self, warn, root=None):
        self.warn, self.items = warn, {}
        self.root = Path(root).resolve() if root is not None else None

    def image(self, src, alt=""):
        data, media = None, ""
        if src.startswith("data:"):
            try:
                header, payload = src.split(",", 1)
                media = header[5:].split(";", 1)[0].lower()
                if len(payload) > LIMIT * 2:
                    raise ValueError("oversize")
                data = base64.b64decode(payload, validate=True) if header.endswith(";base64") else unquote_to_bytes(payload)
            except (ValueError, binascii.Error):
                self.warn("html-resource", "Повреждённый или слишком большой data URI.")
        else:
            split = urlsplit(src)
            if self.root is not None and not split.scheme and not split.netloc and src:
                path = (self.root / unquote(split.path)).resolve()
                if path.is_relative_to(self.root) and path.is_file() and path.stat().st_size <= LIMIT:
                    data, media = path.read_bytes(), mimetypes.guess_type(path)[0] or ""
            if data is None:
                self.warn("html-resource", f"Изображение не загружено: {src[:160]}")
        if data is None:
            return None
        if media == "image/svg+xml":
            try:
                safe = clean_xml(data.decode("utf-8"), "svg", self.warn)
                data = safe.encode("utf-8") if safe else None
            except UnicodeError:
                data = None
        elif media not in RASTER_TYPES:
            data = None
        if data is None or len(data) > LIMIT:
            self.warn("html-resource", "Формат или размер изображения не поддержан.")
            return None
        key = "html-" + hashlib.sha256(data).hexdigest()[:20]
        kind = ResourceKind.VECTOR_IMAGE if media == "image/svg+xml" else ResourceKind.RASTER_IMAGE
        self.items[key] = Resource(key, kind, media, data=data)
        return Image(key, alt_text=alt)

    def svg(self, xml, alt=""):
        safe = clean_xml(xml, "svg", self.warn)
        if safe is None:
            return None
        return self.image("data:image/svg+xml;base64," + base64.b64encode(safe.encode()).decode(), alt)
