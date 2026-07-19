"""Утилиты для работы с LaTeX."""

import re

# Символы, требующие экранирования в LaTeX. Бэкслэш обрабатывается отдельно,
# чтобы избежать повторного экранирования уже добавленных команд (например,
# "\textbackslash{}" не должен превращаться в "\textbackslash\{\}").
_LATEX_SPECIAL = {
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "^": r"\^{}",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "%": r"\%",
    "[": r"\[",
    "]": r"\]",
}

_SPECIAL_RE = re.compile("[" + re.escape("".join(_LATEX_SPECIAL.keys())) + "]")


def escape_latex(text: str) -> str:
    if not text:
        return ""
    # Экранируем бэкслэш первым, заменяя его на уникальный маркер БЕЗ
    # бэкслэша, чтобы последующий regex не принял добавленные "\{" за
    # пользовательский бэкслэш.
    text = text.replace("\\", "\x00TB\x00")
    # Один проход regex'ом по остальным спецсимволам ({ } $ & # ^ _ ~ % [ ]).
    text = _SPECIAL_RE.sub(lambda m: _LATEX_SPECIAL[m.group()], text)
    # Маркер -> корректная LaTeX-команда "\textbackslash{}" (фигурные скобки
    # нужны команде и не требуют повторного экранирования).
    return text.replace("\x00TB\x00", r"\textbackslash{}").replace("…", r"\dots{}")


__all__ = ["escape_latex"]
