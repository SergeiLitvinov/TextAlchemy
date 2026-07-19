"""Тесты escape_latex."""
from textalchemy.core.latex import escape_latex


def test_escape_empty():
    assert escape_latex("") == ""


def test_escape_plain():
    assert escape_latex("hello world") == "hello world"


def test_escape_braces():
    assert escape_latex("{a}") == r"\{a\}"


def test_escape_backslash_not_double_escaped():
    # Бэкслэш экранируется один раз; добавленные "{" "}" не должны
    # повторно экранироваться (классический баг однопроходной замены).
    out = escape_latex(r"a\b")
    assert out == r"a\textbackslash\{\}b"
    # Нет двойного экранирования бэкслэша.
    assert r"\\textbackslash" not in out


def test_escape_special_no_double_escape():
    out = escape_latex("a{b}c\\d~e%f")
    assert out == r"a\{b\}c\textbackslash\{\}d\textasciitilde{}e\%f"
    # Не должно быть двойного экранирования бэкслэша (исходный "\\" -> "\textbackslash{}").
    assert r"\\textbackslash" not in out


def test_escape_underscore_and_caret():
    assert escape_latex("a_b^c") == r"a\_b\^{}c"


def test_escape_ellipsis():
    assert escape_latex("a…b") == r"a\dots{}b"
