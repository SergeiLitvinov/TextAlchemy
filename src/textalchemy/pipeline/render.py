"""Рендеринг из структурного ``Text`` в целевые форматы.

Каждый рендерер — ``@operation``, на вход ``Text`` (или список ``BibItem``),
на выход — строка/путь. Контракт единый: ``render(text, **opts) -> str``.
Это позволяет собирать пайплайны типа::

    - ingest.file
    - extract.text
    - render.latex
    - store.write

без зависимостей от исходного формата документа.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence, Union

from textalchemy.core.document_model import DocumentModel
from textalchemy.core.registry import operation
from textalchemy.core.types import BibItem, Text

logger = logging.getLogger(__name__)


def _normalize_items(items: Sequence[Any]) -> list[BibItem]:
    """Принять ``[BibItem, ...]`` или ``[dict, ...]`` — вернуть ``[BibItem, ...]``.

    Делегирует ``BibItem.from_dict`` для словарей (поддерживает legacy-ключ
    ``raw`` вместо ``raw_text``) и пропускает готовые ``BibItem`` как есть.
    """
    out: list[BibItem] = []
    for it in items:
        if isinstance(it, BibItem):
            out.append(it)
        elif isinstance(it, dict):
            out.append(BibItem.from_dict(it))
        else:
            raise TypeError(f"unsupported item type: {type(it)}")
    return out


@operation(
    "render.latex",
    input_type="Text",
    output_type="str",
    input_param="text",
    description="Text → LaTeX (статья, с преамблой).",
    tags=["render"],
)
def render_latex(*, text: Text, title: str = "Document", author: str = "Author") -> str:
    from opendoc_formats.writers.text_render import render_latex as render

    return render(text=text, title=title, author=author)


@operation(
    "render.latex.pandoc",
    input_type="Text",
    output_type="str",
    input_param="text",
    description="Text → LaTeX через pandoc (требует установленный pandoc).",
    tags=["render", "external"],
)
def render_latex_pandoc(*, text: Text, input_path: Union[str, Path, None] = None) -> str:
    from opendoc_formats.writers.text_render import render_latex_pandoc as render

    return render(text=text, input_path=input_path)


@operation(
    "render.docx",
    input_type="Text",
    output_type="Path",
    input_param="text",
    description="Text → DOCX (через python-docx).",
    tags=["render"],
)
def render_docx(*, text: Text, output_path: Union[str, Path]) -> Path:
    from opendoc_formats.writers.text_render import render_docx as render

    return render(text=text, output_path=output_path)


@operation(
    "render.bibtex",
    input_type="list[BibItem]",
    output_type="str",
    input_param="items",
    description="BibItem[] → BibTeX (.bib).",
    tags=["render"],
)
def render_bibtex(*, items: Sequence[Any]) -> str:
    """Минимальный BibTeX-рендер: генерирует ``@misc`` записи (как старая версия).

    Принимает ``[BibItem]`` или ``[dict]`` (из YAML)."""
    items = _normalize_items(items)
    lines: list[str] = []
    for i, item in enumerate(items, start=1):
        key = f"item{i:03d}"
        title = (item.title or item.raw_text or "").replace("\n", " ").strip()
        author = " and ".join(item.authors) if item.authors else "Unknown"
        year = str(item.year) if item.year else ""
        lines.append(f"@misc{{{key},")
        lines.append(f"  author = {{{author}}},")
        if title:
            lines.append(f"  title  = {{{title}}},")
        if year:
            lines.append(f"  year   = {{{year}}},")
        if item.doi:
            lines.append(f"  doi    = {{{item.doi}}},")
        if item.url:
            lines.append(f"  url    = {{{item.url}}},")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


@operation(
    "render.gost",
    input_type="list[BibItem]",
    output_type="str",
    input_param="items",
    description="BibItem[] → ГОСТ Р 7.0.100.",
    tags=["render"],
)
def render_gost(*, items: Sequence[Any]) -> str:
    """Рендер по ГОСТ через ``organize.gost.GostFormatter`` (единый источник истины).

    Принимает ``[BibItem]`` или ``[dict]``.
    """
    from textalchemy.organize.gost import GostFormatter

    items = _normalize_items(items)
    return GostFormatter().format_bibliography(items)


@operation(
    "render.markdown",
    input_type="list[BibItem]",
    output_type="str",
    input_param="items",
    description="BibItem[] → Markdown список.",
    tags=["render"],
)
def render_markdown(*, items: Sequence[Any]) -> str:
    lines: list[str] = []
    items = _normalize_items(items)
    for item in items:
        authors = ", ".join(item.authors) if item.authors else "Без автора"
        year = f" ({item.year})" if item.year else ""
        title = f"**{item.title}**" if item.title else ""
        lines.append(f"{item.index}. {authors}{year}. {title}")
    return "\n".join(lines)


@operation(
    "render.docx_model",
    input_type="DocumentModel",
    output_type="Path",
    input_param="document",
    description="DocumentModel → DOCX через write_docx_model.",
    tags=["render", "docx", "document-model"],
)
def render_docx_model(*, document: DocumentModel, output_path: Union[str, Path]) -> Path:
    from textalchemy.convert.docx_writer import write_docx_model
    from textalchemy.core.exceptions import ConvertError

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    report = write_docx_model(document, out)
    if not report.success:
        errors = [i.message for i in report.issues if i.severity.value == "error"]
        msg = "; ".join(errors) if errors else "write_docx_model returned success=False"
        raise ConvertError(msg)
    return out


@operation(
    "render.pptx_model",
    input_type="DocumentModel",
    output_type="dict",
    input_param="document",
    description="Модель → редактируемый PPTX с отчётом о потерях.",
    tags=["render", "pptx", "document-model"],
)
def render_pptx_model(*, document: DocumentModel, output_path: Union[str, Path]) -> dict:
    from textalchemy.convert.pptx_writer import write_pptx_model

    return write_pptx_model(document, output_path).to_dict()


@operation(
    "render.txt_model",
    input_type="DocumentModel",
    output_type="dict",
    input_param="document",
    description="Модель → текст UTF-8 с отчётом о потерях.",
    tags=["render", "txt", "document-model"],
)
def render_txt_model(*, document: DocumentModel, output_path: Union[str, Path]) -> dict:
    from textalchemy.convert.txt_writer import write_txt_model

    return write_txt_model(document, output_path).to_dict()


@operation(
    "render.json",
    input_type="list[BibItem]",
    output_type="str",
    input_param="items",
    description="BibItem[] → JSON.",
    tags=["render"],
)
def render_json(*, items: Sequence[Any]) -> str:
    import json

    items = _normalize_items(items)
    return json.dumps(
        [
            {
                "index": i.index,
                "authors": i.authors,
                "title": i.title,
                "year": i.year,
                "doc_type": i.doc_type,
                "source": i.source,
                "pages": i.pages,
                "doi": i.doi,
                "isbn": i.isbn,
                "url": i.url,
                "raw": i.raw_text,
            }
            for i in items
        ],
        ensure_ascii=False,
        indent=2,
    )


__all__ = [
    "render_latex",
    "render_latex_pandoc",
    "render_docx",
    "render_docx_model",
    "render_bibtex",
    "render_gost",
    "render_markdown",
    "render_json",
]
