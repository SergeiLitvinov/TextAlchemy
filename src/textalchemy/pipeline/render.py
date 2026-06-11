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

from textalchemy.core.registry import operation
from textalchemy.core.types import BibItem, Text

logger = logging.getLogger(__name__)


def _normalize_items(items: Sequence[Any]) -> list[BibItem]:
    """Принять ``[BibItem, ...]`` или ``[dict, ...]`` — вернуть ``[BibItem, ...]``."""
    out: list[BibItem] = []
    for it in items:
        if isinstance(it, BibItem):
            out.append(it)
        elif isinstance(it, dict):
            kwargs = {k: v for k, v in it.items() if k in BibItem.__dataclass_fields__}
            kwargs.setdefault("index", len(out) + 1)
            kwargs.setdefault("raw_text", it.get("raw", "") or it.get("title", ""))
            out.append(BibItem(**kwargs))
        else:
            raise TypeError(f"unsupported item type: {type(it)}")
    return out


_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "{": r"\{", "}": r"\}",
    "$": r"\$", "&": r"\&", "#": r"\#",
    "^": r"\^{}", "_": r"\_",
    "~": r"\textasciitilde{}",
    "%": r"\%",
    "[": r"\[", "]": r"\]",
}


def _escape_latex(text: str) -> str:
    if not text:
        return ""
    for c, repl in _LATEX_SPECIAL.items():
        text = text.replace(c, repl)
    return text.replace("…", r"\dots{}")


_PREAMBLE = (
    r"\documentclass[12pt,a4paper]{article}" "\n"
    r"\usepackage[T2A]{fontenc}" "\n"
    r"\usepackage[utf8]{inputenc}" "\n"
    r"\usepackage[russian]{babel}" "\n"
    r"\usepackage{amsmath,amssymb}" "\n"
    r"\usepackage{graphicx}" "\n"
    r"\usepackage{geometry}" "\n"
    r"\geometry{left=3cm,right=1.5cm,top=2cm,bottom=2cm}" "\n"
    r"\usepackage{setspace}" "\n"
    r"\onehalfspacing" "\n"
)


@operation(
    "render.latex", input_type="Text", output_type="str", input_param="text",
    description="Text → LaTeX (статья, с преамблой).", tags=["render"],
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

    for block in text.blocks:
        if block.type.value == "heading":
            level = max(1, min(block.level or 1, 3))
            cmd = ("section", "subsection", "subsubsection")[level - 1]
            parts.append(rf"\{cmd}{{{_escape_latex(block.text)}}}")
            parts.append("")
        else:
            parts.append(_escape_latex(block.text))
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
    "render.latex.pandoc", input_type="Text", output_type="str", input_param="text",
    description="Text → LaTeX через pandoc (требует установленный pandoc).",
    tags=["render", "external"],
)
def render_latex_pandoc(*, text: Text, input_path: Union[str, Path, None] = None) -> str:
    """Если есть ``input_path`` (DOCX), конвертирует pandoc-ом. Иначе fallback на ``render.latex``."""
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("pandoc"):
        logger.warning("pandoc не найден, fallback на render.latex")
        return render_latex(text)

    if input_path is None:
        return render_latex(text)

    with tempfile.NamedTemporaryFile(suffix=".tex", delete=False, mode="w", encoding="utf-8") as f:
        out = Path(f.name)
    try:
        subprocess.run(
            ["pandoc", str(input_path), "-o", str(out),
             "--from", "docx", "--to", "latex",
             "--standalone", "--top-level-division=chapter"],
            check=True, capture_output=True, text=True, timeout=120,
        )
        return out.read_text(encoding="utf-8")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("pandoc failed: %s, fallback на render.latex", e)
        return render_latex(text)
    finally:
        out.unlink(missing_ok=True)


@operation(
    "render.docx", input_type="Text", output_type="Path", input_param="text",
    description="Text → DOCX (через python-docx).", tags=["render"],
)
def render_docx(*, text: Text, output_path: Union[str, Path]) -> Path:
    """Записать ``Text`` в DOCX. Возвращает путь к созданному файлу."""
    from docx import Document

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
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
    d.save(str(out))
    return out


@operation(
    "render.bibtex", input_type="list[BibItem]", output_type="str",
    description="BibItem[] → BibTeX (.bib).", tags=["render"],
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
    "render.gost", input_type="list[BibItem]", output_type="str",
    description="BibItem[] → ГОСТ Р 7.0.100.", tags=["render"],
)
def render_gost(*, items: Sequence[Any]) -> str:
    """Простой рендер по ГОСТ: авторы, заглавие, // источник, год, страницы, DOI.

    Полная реализация лежит в ``organize/gost.py``; здесь — конвейерная
    обёртка, работающая с ``BibItem`` напрямую (без зависимости на organize/).
    Принимает ``[BibItem]`` или ``[dict]``.
    """
    items = _normalize_items(items)
    def fa(authors: list[str]) -> str:
        return ", ".join(authors) if authors else "Без автора"

    out: list[str] = []
    for i, item in enumerate(items, start=1):
        parts: list[str] = [fa(item.authors), item.title or item.raw_text]
        if item.source:
            parts.append(f"// {item.source}")
        if item.year:
            parts.append(f". – {item.year}")
        if item.pages:
            parts.append(f". – {item.pages}")
        if item.doi:
            parts.append(f". – DOI: {item.doi}")
        if item.isbn:
            parts.append(f". – ISBN: {item.isbn}")
        out.append(f"{i}. " + " ".join(parts))
    return "\n\n".join(out)


@operation(
    "render.markdown", input_type="list[BibItem]", output_type="str",
    description="BibItem[] → Markdown список.", tags=["render"],
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
    "render.json", input_type="list[BibItem]", output_type="str",
    description="BibItem[] → JSON.", tags=["render"],
)
def render_json(*, items: Sequence[Any]) -> str:
    import json
    items = _normalize_items(items)
    return json.dumps(
        [
            {
                "index": i.index, "authors": i.authors, "title": i.title,
                "year": i.year, "doc_type": i.doc_type, "source": i.source,
                "pages": i.pages, "doi": i.doi, "isbn": i.isbn, "url": i.url,
                "raw": i.raw_text,
            }
            for i in items
        ],
        ensure_ascii=False, indent=2,
    )


__all__ = [
    "render_latex",
    "render_latex_pandoc",
    "render_docx",
    "render_bibtex",
    "render_gost",
    "render_markdown",
    "render_json",
]
