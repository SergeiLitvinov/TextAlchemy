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
from textalchemy.core.latex import escape_latex as _escape_latex
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


_PREAMBLE = (
    r"\documentclass[12pt,a4paper]{article}"
    "\n"
    r"\usepackage[T2A]{fontenc}"
    "\n"
    r"\usepackage[utf8]{inputenc}"
    "\n"
    r"\usepackage[russian]{babel}"
    "\n"
    r"\usepackage{amsmath,amssymb}"
    "\n"
    r"\usepackage{graphicx}"
    "\n"
    r"\usepackage{geometry}"
    "\n"
    r"\geometry{left=3cm,right=1.5cm,top=2cm,bottom=2cm}"
    "\n"
    r"\usepackage{setspace}"
    "\n"
    r"\onehalfspacing"
    "\n"
)


@operation(
    "render.latex",
    input_type="Text",
    output_type="str",
    input_param="text",
    description="Text → LaTeX (статья, с преамблой).",
    tags=["render"],
)
def render_latex(*, text: Text, title: str = "Document", author: str = "Author") -> str:
    """Минимальный LaTeX-рендер: заголовок, абзацы, таблицы.

    Сложная вёрстка (стили, списки, изображения) намеренно упрощена —
    для научных текстов обычно достаточно. Если нужна полная конвертация,
    используйте ``render.latex.pandoc`` (требует установленный ``pandoc``).
    """
    parts: list[str] = [_PREAMBLE, r"\begin{document}", ""]
    parts.append(rf"\title{{{_escape_latex(title)}}}")
    parts.append(rf"\author{{{_escape_latex(author)}}}")
    parts.append(r"\date{\today}")
    parts.append(r"\maketitle")
    parts.append("")

    in_list = False
    for block in text.blocks:
        if block.type.value == "heading":
            if in_list:
                parts.append(r"\end{itemize}")
                parts.append("")
                in_list = False
            level = max(1, min(block.level or 1, 3))
            cmd = ("section", "subsection", "subsubsection")[level - 1]
            parts.append(rf"\{cmd}{{{_escape_latex(block.text)}}}")
            parts.append("")
        elif block.type.value == "list_item":
            if not in_list:
                parts.append(r"\begin{itemize}")
                parts.append("")
                in_list = True
            parts.append(rf"\item {_escape_latex(block.text)}")
        else:
            if in_list:
                parts.append(r"\end{itemize}")
                parts.append("")
                in_list = False
            if block.type.value == "code" or block.type.value == "equation":
                parts.append(block.text)
            else:
                parts.append(_escape_latex(block.text))
            parts.append("")
    if in_list:
        parts.append(r"\end{itemize}")
        parts.append("")

    for table in text.tables:
        if not table.rows:
            continue
        cols = max((len(r) for r in table.rows), default=0)
        spec = "|" + "|".join(["c"] * cols) + "|"
        parts.append(rf"\begin{{tabular}}{{{spec}}}")
        parts.append(r"\hline")
        for row in table.rows:
            cells = [_escape_latex(c) for c in row]
            parts.append(" & ".join(cells) + r" \\")
            parts.append(r"\hline")
        parts.append(r"\end{tabular}")
        parts.append("")

    parts.append(r"\end{document}")
    return "\n".join(parts)


@operation(
    "render.latex.pandoc",
    input_type="Text",
    output_type="str",
    input_param="text",
    description="Text → LaTeX через pandoc (требует установленный pandoc).",
    tags=["render", "external"],
)
def render_latex_pandoc(*, text: Text, input_path: Union[str, Path, None] = None) -> str:
    """Если есть ``input_path`` (DOCX), конвертирует pandoc-ом. Иначе fallback на ``render.latex``."""
    import shutil
    import subprocess

    if not shutil.which("pandoc"):
        logger.warning("pandoc не найден, fallback на render.latex")
        return render_latex(text=text)

    if input_path is None:
        return render_latex(text=text)

    from textalchemy.core.artifacts import ArtifactWorkspace

    try:
        with ArtifactWorkspace(prefix="textalchemy_pandoc_") as workspace:
            out = workspace.artifact_path("output.tex")
            subprocess.run(
                [
                    "pandoc",
                    str(input_path),
                    "-o",
                    str(out),
                    "--from",
                    "docx",
                    "--to",
                    "latex",
                    "--standalone",
                    "--top-level-division=chapter",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            workspace.validate_artifact(out)
            return out.read_text(encoding="utf-8")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as error:
        logger.warning("pandoc failed: %s, fallback на render.latex", error)
        return render_latex(text=text)


@operation(
    "render.docx",
    input_type="Text",
    output_type="Path",
    input_param="text",
    description="Text → DOCX (через python-docx).",
    tags=["render"],
)
def render_docx(*, text: Text, output_path: Union[str, Path]) -> Path:
    """Записать ``Text`` в DOCX. Возвращает путь к созданному файлу."""
    import io

    from docx import Document

    from textalchemy.core.io import atomic_write_bytes

    out = Path(output_path)
    d = Document()
    for block in text.blocks:
        if block.type.value == "heading":
            level = max(1, min(block.level or 1, 3))
            d.add_heading(block.text, level=level)
        else:
            d.add_paragraph(block.text)
    for table in text.tables:
        if not table.rows:
            continue
        cols = max((len(r) for r in table.rows), default=0)
        t = d.add_table(rows=len(table.rows), cols=cols)
        for i, row in enumerate(table.rows):
            for j, cell in enumerate(row):
                if j < cols:
                    t.cell(i, j).text = cell
    buffer = io.BytesIO()
    d.save(buffer)
    atomic_write_bytes(out, buffer.getvalue())
    return out


@operation(
    "render.bibtex",
    input_type="list[BibItem]",
    output_type="str",
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
    "render.pptx_model", input_type="DocumentModel", output_type="dict", input_param="document",
    description="Модель → редактируемый PPTX с отчётом о потерях.", tags=["render", "pptx", "document-model"],
)
def render_pptx_model(*, document: DocumentModel, output_path: Union[str, Path]) -> dict:
    from textalchemy.convert.pptx_writer import write_pptx_model

    return write_pptx_model(document, output_path).to_dict()


@operation(
    "render.json",
    input_type="list[BibItem]",
    output_type="str",
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
