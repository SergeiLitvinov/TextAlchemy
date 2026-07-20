"""Конвертер DOCX → LaTeX.

Читает .docx через python-docx, восстанавливает структуру (заголовки,
абзацы, списки, таблицы, базовое выделение жирным/курсивом и встроенные
формулы OMML) и отдаёт готовый ``.tex``. Текст сохраняется как текст
(никаких растровых вставок страниц).
"""
from __future__ import annotations

from pathlib import Path

from textalchemy.convert.base import BaseConverter, ConversionResult
from textalchemy.core.latex import escape_latex as _escape_latex
from textalchemy.core.types import Block, BlockType, Table, Text
from textalchemy.pipeline.render import _PREAMBLE


def _run_text(run) -> str:
    """Текст прогона с inline-выделением (жирный/курсив)."""
    txt = run.text or ""
    if not txt:
        return ""
    if run.bold and run.italic:
        return r"\textbf{\textit{" + _escape_latex(txt) + "}}"
    if run.bold:
        return r"\textbf{" + _escape_latex(txt) + "}"
    if run.italic:
        return r"\textit{" + _escape_latex(txt) + "}"
    return _escape_latex(txt)


def _para_to_latex(para) -> str:
    return "".join(_run_text(r) for r in para.runs)


def _table_to_latex(table: Table) -> str:
    rows = table.rows
    if not rows:
        return ""
    ncols = max(len(r) for r in rows)
    spec = "|" + "|".join(["l"] * ncols) + "|"
    lines = [r"\begin{table}[ht]", r"\centering", rf"\begin{{tabular}}{{{spec}}}", r"\hline"]
    for row in rows:
        cells = [_escape_latex(c) for c in row]
        while len(cells) < ncols:
            cells.append("")
        lines.append(" & ".join(cells) + r" \\")
        lines.append(r"\hline")
    lines.append(r"\end{tabular}")
    lines.append(r"\end{table}")
    return "\n".join(lines)


class DocxToLatexConverter(BaseConverter):
    @property
    def name(self) -> str:
        return "docx2latex"

    def convert(self, input_path: str | Path, output_path: str | Path) -> ConversionResult:
        prepared = self._prepare(input_path, output_path)
        if prepared is None:
            return ConversionResult(Path(input_path), Path(output_path), False, "Input file not found")
        input_path, output_path = prepared
        try:
            from docx import Document as DocxDocument
            from docx.oxml.ns import qn
        except ImportError:
            return ConversionResult(
                input_path, output_path, False,
                "python-docx не установлен (добавьте в зависимости для DOCX→LaTeX)",
            )

        try:
            doc = DocxDocument(str(input_path))
            from textalchemy.core.types import DocFormat
            text = Text(source_format=DocFormat.DOCX)
            text.engine = "docx2latex"

            def _is_equation(para) -> str | None:
                # Встроенная формула (OMML) внутри параграфа.
                try:
                    omml = para._p.find(".//" + qn("w:object"))
                    if omml is not None:
                        return r"\begin{equation*}" + "\n" + r"\text{(формула OMML)}" + "\n" + r"\end{equation*}"
                except Exception:  # noqa: BLE001
                    pass
                return None

            for para in doc.paragraphs:
                style = (para.style.name or "") if para.style else ""
                content = _para_to_latex(para).strip()
                if not content:
                    continue

                if style.startswith("Heading") or style.startswith("Title"):
                    try:
                        level = int(style.replace("Heading", "").strip() or "1")
                    except ValueError:
                        level = 1
                    if style.startswith("Title"):
                        level = 1
                    level = max(1, min(level, 3))
                    text.blocks.append(Block(type=BlockType.HEADING, text=content, level=level))
                elif style.startswith("List") or style.startswith("List Bullet") or style.startswith("List Number"):
                    text.blocks.append(Block(type=BlockType.LIST_ITEM, text=content))
                else:
                    eq = _is_equation(para)
                    if eq is not None:
                        text.blocks.append(Block(type=BlockType.EQUATION, text=eq))
                    else:
                        text.blocks.append(Block(type=BlockType.PARAGRAPH, text=content))

            for table in doc.tables:
                text.tables.append(Table(rows=[[c.text.strip() for c in row.cells] for row in table.rows]))

            tex = self._render(text, title=input_path.stem)
            Path(output_path).write_text(tex, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            return ConversionResult(input_path, output_path, False, str(e))

        return ConversionResult(input_path, output_path, output_path.exists())

    @staticmethod
    def _render(text: Text, title: str) -> str:
        parts: list[str] = [_PREAMBLE, r"\begin{document}", ""]
        parts.append(rf"\title{{{_escape_latex(title)}}}")
        parts.append(r"\author{}")
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
                parts.append(rf"\{cmd}{{{block.text}}}")
                parts.append("")
            elif block.type.value == "list_item":
                if not in_list:
                    parts.append(r"\begin{itemize}")
                    parts.append("")
                    in_list = True
                parts.append(rf"\item {block.text}")
            else:
                if in_list:
                    parts.append(r"\end{itemize}")
                    parts.append("")
                    in_list = False
                if block.type.value == "equation":
                    parts.append(block.text)
                else:
                    parts.append(block.text)
                parts.append("")

        if in_list:
            parts.append(r"\end{itemize}")
            parts.append("")

        for table in text.tables:
            if table.rows:
                parts.append(_table_to_latex(table))
                parts.append("")

        parts.append(r"\end{document}")
        return "\n".join(parts)
