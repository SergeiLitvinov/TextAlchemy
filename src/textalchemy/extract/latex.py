import subprocess
from pathlib import Path

from textalchemy.core.exceptions import ExtractError
from textalchemy.core.io import check_archive_safety
from textalchemy.core.latex import escape_latex as clean_text


def _docx():
    """Ленивый импорт python-docx (дополнительная зависимость `docx`)."""
    from docx import Document  # type: ignore[import-not-found]

    return Document


def _wd_align():
    """Ленивый импорт ``WD_ALIGN_PARAGRAPH`` из python-docx."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore[import-not-found]

    return WD_ALIGN_PARAGRAPH


def _get_paragraph_style(paragraph):
    style_name = paragraph.style.name.lower() if paragraph.style and paragraph.style.name else ""
    if "heading 1" in style_name or "заголовок 1" in style_name:
        return "section"
    if "heading 2" in style_name or "заголовок 2" in style_name:
        return "subsection"
    if "heading 3" in style_name or "заголовок 3" in style_name:
        return "subsubsection"
    if "title" in style_name or "название" in style_name:
        return "title"
    return None


_PREAMBLE = """\\documentclass[12pt,a4paper]{article}
\\usepackage[T2A]{fontenc}
\\usepackage[utf8]{inputenc}
\\usepackage[russian]{babel}
\\usepackage{amsmath,amssymb}
\\usepackage{graphicx}
\\usepackage{geometry}
\\geometry{left=3cm,right=1.5cm,top=2cm,bottom=2cm}
\\usepackage{setspace}
\\onehalfspacing
"""


def docx_to_latex(input_path: str | Path, output_path: str | Path | None = None, doc_type: str = "manuscript") -> str:
    input_path = Path(input_path)
    if not input_path.exists():
        raise ExtractError(f"File not found: {input_path}")
    try:
        check_archive_safety(input_path)
        doc = _docx()(str(input_path))
    except Exception as e:
        raise ExtractError(f"Failed to read document: {e}") from e

    lines = [_PREAMBLE, "\\begin{document}"]
    if doc_type == "abstract":
        lines.append("\\thispagestyle{empty}")
    lines.append("")

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            lines.append("")
            continue
        style = _get_paragraph_style(para)
        clean = clean_text(text)
        if style == "title":
            continue
        elif style == "section":
            lines.append(f"\\section{{{clean}}}")
        elif style == "subsection":
            lines.append(f"\\subsection{{{clean}}}")
        elif style == "subsubsection":
            lines.append(f"\\subsubsection{{{clean}}}")
        else:
            align = para.alignment
            if align == _wd_align().CENTER:
                lines.append(f"\\begin{{center}}{clean}\\end{{center}}")
            elif align == _wd_align().RIGHT:
                lines.append(f"\\begin{{flushright}}{clean}\\end{{flushright}}")
            else:
                lines.append(clean)
        lines.append("")

    for table in doc.tables:
        if not table.rows:
            continue
        col_count = len(table.columns)
        col_spec = "|" + "|".join(["c"] * col_count) + "|"
        lines.append(f"\\begin{{tabular}}{{{col_spec}}}")
        lines.append("\\hline")
        for row in table.rows:
            cells = [clean_text(cell.text.strip()) for cell in row.cells]
            lines.append(" & ".join(cells) + " \\\\")
            lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("")

    lines.append("\\end{document}")
    result = "\n".join(lines)

    if output_path:
        from textalchemy.core.io import atomic_write_text

        atomic_write_text(output_path, result, encoding="utf-8")
    return result


def docx_to_latex_pandoc(input_path: str | Path, output_path: str | Path, doc_type: str = "manuscript") -> str:
    from textalchemy.core.artifacts import ArtifactWorkspace
    from textalchemy.core.io import atomic_write_text

    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.exists():
        raise ExtractError(f"File not found: {input_path}")

    lua_filter = Path(__file__).parent.parent / "extract" / "lua-filters" / "sanitize.lua"
    lua_filter_str = str(lua_filter) if lua_filter.exists() else ""

    with ArtifactWorkspace(prefix="textalchemy_pandoc_") as workspace:
        staged = workspace.artifact_path("output.tex")
        cmd = [
            "pandoc",
            str(input_path),
            "-o",
            str(staged),
            "--from",
            "docx",
            "--to",
            "latex",
            "--standalone",
            "--top-level-division=chapter",
        ]
        if lua_filter_str:
            cmd.extend(["--lua-filter", lua_filter_str])

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)
        except FileNotFoundError as error:
            raise ExtractError("pandoc not found. Install pandoc or use 'latex' (python-docx) format.") from error
        except subprocess.TimeoutExpired as error:
            raise ExtractError("pandoc timed out") from error
        except subprocess.CalledProcessError as error:
            raise ExtractError(f"pandoc error: {error.stderr[:500]}") from error

        workspace.validate_artifact(staged)
        tex = staged.read_text(encoding="utf-8")
        title_text = "Document"
        author_text = "Author"
        russian_support = (
            "\\usepackage[T2A]{fontenc}\n"
            "\\usepackage[utf8]{inputenc}\n"
            "\\usepackage[russian]{babel}\n"
            "\\usepackage{amsmath,amsfonts,amssymb}\n"
            "\\usepackage{graphicx}\n"
            "\\usepackage{geometry}\n"
            "\\geometry{a4paper, margin=2cm}\n"
        )
        tex = tex.replace("\\begin{document}", russian_support + "\n\\begin{document}")
        tex = tex.replace(
            "\\maketitle",
            f"\\title{{{title_text}}}\n\\author{{{author_text}}}\n\\date{{\\today}}\n\\maketitle",
        )
        atomic_write_text(output_path, tex, encoding="utf-8")
        return tex
