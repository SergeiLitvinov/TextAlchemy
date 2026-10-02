"""Структурная инспекция документов и промежуточной модели."""

from __future__ import annotations

import base64
import hashlib
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from opendoc.inspection import (
    DocumentComparison as DocumentComparison,
)
from opendoc.inspection import (
    DocumentInspection as DocumentInspection,
)
from opendoc.inspection import (
    _compare_fonts as _compare_fonts,
)
from opendoc.inspection import (
    _compare_objects as _compare_objects,
)
from opendoc.inspection import (
    _compare_page_geometry as _compare_page_geometry,
)
from opendoc.inspection import (
    _compare_resources as _compare_resources,
)
from opendoc.inspection import (
    _font_substitution_candidates as _font_substitution_candidates,
)
from opendoc.inspection import (
    _inspect_block as _inspect_block,
)
from opendoc.inspection import (
    _inspect_box as _inspect_box,
)
from opendoc.inspection import (
    _inspect_formula as _inspect_formula,
)
from opendoc.inspection import (
    _inspect_image as _inspect_image,
)
from opendoc.inspection import (
    _inspect_page as _inspect_page,
)
from opendoc.inspection import (
    _inspect_resource as _inspect_resource,
)
from opendoc.inspection import (
    _json_safe as _json_safe,
)
from opendoc.inspection import (
    _mean as _mean,
)
from opendoc.inspection import (
    _normalise_font_name as _normalise_font_name,
)
from opendoc.inspection import (
    _normalised_fonts as _normalised_fonts,
)
from opendoc.inspection import (
    _quality_metrics as _quality_metrics,
)
from opendoc.inspection import (
    _ratio as _ratio,
)
from opendoc.inspection import (
    _resource_identity as _resource_identity,
)
from opendoc.inspection import (
    _rms as _rms,
)
from opendoc.inspection import (
    compare_inspections as compare_inspections,
)
from opendoc.inspection import (
    inspect_document_model as inspect_document_model,
)

from textalchemy.core.diagnostics import IssueSeverity
from textalchemy.core.exceptions import TextAlchemyError


def inspect_path(path: str | Path) -> DocumentInspection:
    """Inspect DOCX, PDF, PPTX, TXT, HTML, LaTeX or a JSON-serialized DocumentModel."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    if suffix == ".txt":
        from textalchemy.formats.txt import read_txt_model

        report = inspect_document_model(read_txt_model(source), source_path=source, source_format="txt")
        # Model defaults are not evidence of pagination in a plain-text source.
        report.pages.clear()
        report.metrics.pop("pages", None)
        return report
    if suffix == ".docx":
        from textalchemy.formats.docx import read_docx_model

        return inspect_document_model(read_docx_model(source), source_path=source, source_format="docx")
    if suffix == ".json":
        from textalchemy.core.document_codec import load_document

        return inspect_document_model(load_document(source), source_path=source, source_format="document-model-json")
    if suffix == ".pdf":
        return _inspect_pdf(source)
    if suffix == ".pptx":
        from textalchemy.formats.pptx import read_pptx_model

        return inspect_document_model(read_pptx_model(source), source_path=source, source_format="pptx")
    if suffix == ".html":
        return _inspect_html(source)
    if suffix == ".tex":
        return _inspect_latex(source)
    raise TextAlchemyError(f"Unsupported inspection format: {suffix or '<none>'}")


def _inspect_pdf(path: Path) -> DocumentInspection:
    import fitz
    from pypdf import PdfReader

    report = DocumentInspection(path, "pdf")
    counters: Counter[str] = Counter()
    fonts: Counter[str] = Counter()
    resources: dict[int, dict[str, Any]] = {}
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            password_status = reader.decrypt("")
        except Exception:  # noqa: BLE001 - damaged encryption dictionaries vary by producer
            password_status = 0
        if not password_status:
            report.add(IssueSeverity.ERROR, "encryption", "PDF requires a password for structural inspection")
            report.metrics = {"encrypted": 1}
            return report
        report.add(IssueSeverity.WARNING, "encryption", "PDF is encrypted with an empty password")
    counters["form_fields"] = len(reader.get_fields() or {})
    counters["pages"] = len(reader.pages)

    with fitz.open(path) as document:
        report.metadata = {key: value for key, value in document.metadata.items() if value}
        for page_index, page in enumerate(document):
            rectangle = page.rect
            report.pages.append(
                {
                    "index": page_index,
                    "width_pt": rectangle.width,
                    "height_pt": rectangle.height,
                    "rotation": page.rotation,
                }
            )
            page_dict = page.get_text("dict")
            text_blocks = [block for block in page_dict.get("blocks", []) if block.get("type") == 0]
            counters["text_blocks"] += len(text_blocks)
            page_characters = 0
            for block in text_blocks:
                for line in block.get("lines", []):
                    counters["text_lines"] += 1
                    for span in line.get("spans", []):
                        counters["text_runs"] += 1
                        page_characters += len(span.get("text", ""))
                        if span.get("font"):
                            fonts[str(span["font"])] += 1
            counters["characters"] += page_characters
            counters["hyperlinks"] += len(page.get_links())
            drawings = page.get_drawings()
            counters["vector_drawings"] += len(drawings)
            images = page.get_images(full=True)
            counters["image_occurrences"] += len(images)
            for item in images:
                xref = int(item[0])
                if xref not in resources:
                    extracted = document.extract_image(xref)
                    data = extracted.get("image", b"")
                    resources[xref] = {
                        "id": f"xref-{xref}",
                        "kind": "raster_image",
                        "media_type": f"image/{extracted.get('ext', 'unknown')}",
                        "filename": None,
                        "size_bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest() if data else None,
                        "embedded": True,
                        "width_px": extracted.get("width"),
                        "height_px": extracted.get("height"),
                    }
            counters["form_widgets"] += len(list(page.widgets() or []))
            if page_characters == 0 and not images and not drawings:
                report.add(
                    IssueSeverity.WARNING,
                    "blank-page",
                    "page has no text, images, or vector drawings",
                    f"pages[{page_index}]",
                )
    counters["resources"] = len(resources)
    report.metrics = dict(sorted(counters.items()))
    report.resources = list(resources.values())
    report.fonts = dict(fonts.most_common())
    return report


_HTML_SKIP_TAGS = {"script", "style", "head"}
_LATEX_MATH_ENVS = (
    "equation",
    "equation*",
    "align",
    "align*",
    "gather",
    "gather*",
    "alignat",
    "alignat*",
    "eqnarray",
    "eqnarray*",
    "multline",
    "multline*",
    "flalign",
    "flalign*",
)
_LATEX_PAPER_SIZES = {
    "a3paper": (841.89, 1190.55),
    "a4paper": (595.28, 841.89),
    "a5paper": (419.53, 595.28),
    "letterpaper": (612.0, 792.0),
    "legalpaper": (612.0, 1008.0),
}
_LATEX_TEXT_COMMANDS = re.compile(r"\\(?:textbf|textit|emph|text|mbox|mathrm|mathsf|mathtt|mathcal|underline|url)\{([^{}]*)\}")
_LATEX_REF_COMMANDS = re.compile(r"\\(?:eqref|pageref|cref|vref|label|ref)\{")
_LATEX_CITE_COMMANDS = re.compile(r"\\[a-zA-Z@]*cite[a-zA-Z@]*\{")
_LATEX_HREF_COMMANDS = re.compile(r"\\href\{")
_LATEX_DISPLAY_MATH = re.compile(r"\$\$.*?\$\$|\\\[.*?\\\]", re.DOTALL)
_LATEX_INLINE_MATH = re.compile(r"(?<!\\)\$(?!\$)[^$\n]+(?<!\\)\$")
_LATEX_HEADING_COMMANDS = re.compile(r"\\(?:chapter|(?:sub)*section)\*?\{")
_LATEX_COMMAND_TOKEN = re.compile(r"\\[a-zA-Z@]+\*?")
_LATEX_BEGIN_END = re.compile(r"\\(?:begin|end)\{[a-zA-Z*]+\}")
_LATEX_ESCAPES = {
    r"\%": "%",
    r"\&": "&",
    r"\_": "_",
    r"\#": "#",
    r"\$": "$",
    r"\{": "{",
    r"\}": "}",
    r"\textbackslash": "\\",
    r"\textasciitilde": "~",
    r"\textasciicircum": "^",
    r"\ldots": "…",
    r"\textendash": "–",
    r"\textemdash": "—",
    r"\textquotedbl": '"',
    r"\textquoteleft": "‘",
    r"\textquoteright": "’",
    r"\textbullet": "•",
}


class _HtmlInspectionParser(HTMLParser):
    """Собрать структурные метрики и data-URI ресурсы из HTML."""

    def __init__(self, report: DocumentInspection) -> None:
        super().__init__(convert_charrefs=True)
        self.report = report
        self.counters: Counter[str] = Counter()
        self.fonts: Counter[str] = Counter()
        self.resources: dict[str, dict[str, Any]] = {}
        self._skip_depth = 0
        self._math_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if tag in _HTML_SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "section":
            self.counters["sections"] += 1
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.counters["headings"] += 1
        elif tag == "p":
            self.counters["paragraphs"] += 1
        elif tag == "table":
            self.counters["tables"] += 1
        elif tag == "tr":
            self.counters["table_rows"] += 1
        elif tag in {"td", "th"}:
            self.counters["table_cells"] += 1
        elif tag == "img":
            self.counters["images"] += 1
            self._inspect_image(attributes.get("src", ""))
        elif tag == "a":
            href = attributes.get("href")
            if href:
                if href.startswith("#"):
                    self.counters["internal_hyperlinks"] += 1
                else:
                    self.counters["hyperlinks"] += 1
        elif tag == "math":
            self.counters["formulas"] += 1
            self._math_depth += 1
        elif tag in {"ul", "ol"}:
            self.counters["lists"] += 1
        elif tag == "li":
            self.counters["list_items"] += 1
        style = attributes.get("style")
        if style:
            self._extract_fonts(style)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in _HTML_SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "math":
            self._math_depth = max(0, self._math_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._math_depth or not data.strip():
            return
        self.counters["characters"] += len(data)
        self.counters["text_runs"] += 1

    def _inspect_image(self, source: str) -> None:
        match = re.match(r"data:(image/[a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=]+)", source)
        if not match:
            return
        media_type, encoded = match.groups()
        try:
            raw = base64.b64decode(encoded)
        except ValueError:
            return
        index = len(self.resources)
        self.resources[f"img-{index}"] = {
            "id": f"img-{index}",
            "kind": "raster_image",
            "media_type": media_type,
            "filename": None,
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "embedded": True,
        }

    def _extract_fonts(self, style: str) -> None:
        for match in re.finditer(r"font-family\s*:\s*([^;}]+)", style):
            family = match.group(1).strip().strip("'\"").split(",")[0].strip()
            if family:
                self.fonts[family] += 1


def _inspect_html(path: Path) -> DocumentInspection:
    """Собрать структурные метрики, ресурсы и шрифты из HTML-файла."""

    report = DocumentInspection(path, "html")
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="utf-8", errors="replace")
    parser = _HtmlInspectionParser(report)
    parser.feed(raw)
    report.metrics = dict(sorted(parser.counters.items()))
    report.resources = list(parser.resources.values())
    report.fonts = dict(parser.fonts.most_common())
    if parser.counters["formulas"]:
        report.formula_formats = {"mathml": parser.counters["formulas"]}
    return report


def _inspect_latex(path: Path) -> DocumentInspection:
    """Собрать структурные метрики и геометрию страницы из LaTeX-файла."""

    report = DocumentInspection(path, "latex")
    raw = path.read_text(encoding="utf-8", errors="replace")
    counters: Counter[str] = Counter()
    counters["pages"] = 1
    counters["characters"] = len(_strip_latex_text(raw))
    counters["text_runs"] = len(re.findall(r"\S+", _strip_latex_text(raw)))
    counters["headings"] = len(_LATEX_HEADING_COMMANDS.findall(raw))
    counters["tables"] = len(re.findall(r"\\begin\{tabular", raw))
    counters["images"] = len(re.findall(r"\\includegraphics\*?", raw))
    counters["hyperlinks"] = len(_LATEX_HREF_COMMANDS.findall(raw))
    counters["internal_hyperlinks"] = len(_LATEX_REF_COMMANDS.findall(raw))
    counters["citations"] = len(_LATEX_CITE_COMMANDS.findall(raw))
    counters["formulas"] = _count_latex_formulas(raw)
    counters["list_items"] = len(re.findall(r"\\item", raw))
    counters["paragraphs"] = _count_latex_paragraphs(raw)
    papersize = _latex_paper_size(raw)
    report.metrics = dict(sorted(counters.items()))
    if papersize is not None:
        report.pages = [
            {
                "index": 0,
                "width_pt": papersize[0],
                "height_pt": papersize[1],
            }
        ]
    if counters["formulas"]:
        report.formula_formats = {"latex": counters["formulas"]}
    return report


def _latex_paper_size(raw: str) -> tuple[float, float] | None:
    match = re.search(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}", raw)
    options = match.group(0) if match else ""
    for name, size in _LATEX_PAPER_SIZES.items():
        if name in options:
            return size
    return None


def _count_latex_formulas(raw: str) -> int:
    return (
        len(_LATEX_DISPLAY_MATH.findall(raw))
        + len(_LATEX_INLINE_MATH.findall(raw))
        + sum(raw.count(rf"\begin{{{env}}}") for env in _LATEX_MATH_ENVS)
    )


def _count_latex_paragraphs(raw: str) -> int:
    body = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", raw, re.DOTALL)
    source = body.group(1) if body else raw
    return sum(1 for block in re.split(r"\n\s*\n", source) if re.search(r"\w", _strip_latex_text(block)))


def _strip_latex_text(raw: str) -> str:
    text = re.sub(r"(?<!\\)%.*$", "", raw, flags=re.MULTILINE)
    text = _LATEX_DISPLAY_MATH.sub(" ", text)
    for env in _LATEX_MATH_ENVS:
        text = re.sub(rf"\\begin{{{env}}}.*?\\end{{{env}}}", " ", text, flags=re.DOTALL)
    text = _LATEX_INLINE_MATH.sub(" ", text)
    text = re.sub(r"\\href\{[^{}]*\}\{([^{}]*)\}", r"\1", text)
    text = _LATEX_CITE_COMMANDS.sub(" ", text)
    text = _LATEX_REF_COMMANDS.sub(" ", text)
    text = _LATEX_BEGIN_END.sub(" ", text)
    text = _LATEX_TEXT_COMMANDS.sub(r"\1", text)
    text = _LATEX_COMMAND_TOKEN.sub(" ", text)
    for token, replacement in _LATEX_ESCAPES.items():
        text = text.replace(token, replacement)
    text = text.replace("~", " ").replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", text).strip()


__all__ = [
    "DocumentComparison",
    "DocumentInspection",
    "compare_inspections",
    "inspect_document_model",
    "inspect_path",
]
