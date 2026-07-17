"""Утилиты для работы с LaTeX."""

_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "{": r"\{", "}": r"\}",
    "$": r"\$", "&": r"\&", "#": r"\#",
    "^": r"\^{}", "_": r"\_",
    "~": r"\textasciitilde{}",
    "%": r"\%",
    "[": r"\[", "]": r"\]",
}


def escape_latex(text: str) -> str:
    if not text:
        return ""
    for c, repl in _LATEX_SPECIAL.items():
        text = text.replace(c, repl)
    return text.replace("…", r"\dots{}")


__all__ = ["escape_latex"]
