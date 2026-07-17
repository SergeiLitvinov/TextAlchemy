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
    out = []
    for ch in text:
        out.append(_LATEX_SPECIAL.get(ch, ch))
    result = "".join(out)
    return result.replace("…", r"\dots{}")


__all__ = ["escape_latex"]
