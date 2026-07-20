"""Пост-обработка DOCX: восстановление структуры (заголовки) после конвертации.

Движки вроде ``pdf2docx`` часто отдают весь текст стилем ``Normal``,
теряя иерархию разделов. Эвристика ниже восстанавливает заголовки по
размеру шрифта и жирности, чтобы последующие этапы (DOCX→LaTeX,
библиография) видели реальную структуру.
"""
from __future__ import annotations

from pathlib import Path


def _font_size(run) -> float | None:
    try:
        sz = run.font.size
        if sz is not None:
            return sz.pt
    except Exception:  # noqa: BLE001
        pass
    return None


def _paragraph_size(para) -> float | None:
    sizes = [s for s in (_font_size(r) for r in para.runs) if s is not None]
    if not sizes:
        # Без явного размера — считаем базовым (None обработается снаружи).
        return None
    return max(sizes)


def apply_heading_styles(path: str | Path) -> None:
    """Назначить стили ``Heading 1/2/3`` параграфам, похожим на заголовки.

    Правила:
    * размер шрифта заметно больше «базового» (медианы по документу);
    * либо жирный и короткий (< 90 символов) и не список/таблица.
    Заголовки не перезаписываются, если уже имеют стиль Heading/Title.
    """
    from docx import Document as DocxDocument

    doc = DocxDocument(str(path))
    paras = [p for p in doc.paragraphs]

    sizes: list[float] = []
    for p in paras:
        sz = _paragraph_size(p)
        if sz is not None:
            sizes.append(sz)
    if not sizes:
        return
    base = sorted(sizes)[len(sizes) // 2]  # медиана (типичный размер тела)
    max_sz = max(sizes)

    def is_heading_style(style_name: str) -> bool:
        return style_name.startswith("Heading") or style_name.startswith("Title")

    for p in paras:
        if not p.text.strip():
            continue
        style_name = (p.style.name or "") if p.style else ""
        if is_heading_style(style_name):
            continue
        sz = _paragraph_size(p) or base
        bold = any(r.bold for r in p.runs if r.bold)
        short = len(p.text.strip()) <= 90
        is_bigger = sz >= base + 1.5
        looks_heading = is_bigger or (bold and short and sz >= base)
        if not looks_heading:
            continue
        # Уровень по доле от диапазона [base, max] (самый крупный — Heading 1).
        if max_sz > base:
            frac = (sz - base) / (max_sz - base)
        else:
            frac = 1.0
        if frac >= 0.66 or sz >= base + 6:
            level = 1
        elif frac >= 0.33 or sz >= base + 3:
            level = 2
        else:
            level = 3
        try:
            p.style = f"Heading {level}"
        except Exception:  # noqa: BLE001
            # Стиль может отсутствовать в шаблоне — игнорируем.
            pass

    doc.save(str(path))


def ensure_min_font(path: str | Path, min_pt: float = 8.0) -> None:
    """Защита от слишком мелкого шрифта (иногда 1pt после конвертации)."""
    from docx import Document as DocxDocument

    doc = DocxDocument(str(path))
    changed = False
    for p in doc.paragraphs:
        for r in p.runs:
            sz = _font_size(r)
            if sz is not None and sz < min_pt:
                try:
                    r.font.size = None  # вернуть к базовому стиля
                    changed = True
                except Exception:  # noqa: BLE001
                    pass
    if changed:
        doc.save(str(path))
