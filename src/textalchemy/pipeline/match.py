"""Стадия match: (Document, BibItem[]) → Match.

Оперирует ``Text`` (если есть) и ``filename`` из ``Document``. Каждый
``BibItem`` оценивается набором сигналов (см. ``signals.py``); побеждает
item с максимальным суммарным score. Если score ниже порога — ``Match.matched=False``.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from textalchemy.core.registry import operation
from textalchemy.core.types import BibItem, Document, Match, Text


@operation(
    "match.bibliography",
    input_type="Text",
    output_type="Match",
    input_param="text",
    description="Сопоставить документ со списком BibItem по сигналам.",
    tags=["match"],
)
def match_bibliography(
    *,
    text: Text,
    document: Document,
    items: list[BibItem],
    threshold: float = 0.30,
    manual: Optional[dict[str, int]] = None,
    weights: Optional[dict[str, float]] = None,
) -> Match:
    """Скоринг всех ``BibItem`` против одного документа.

    Возвращает ``Match`` с лучшим кандидатом. ``Match.matched=True`` если
    ``score >= threshold``.
    """
    from textalchemy.pipeline.signals import collect_signals, manual_match

    filename = Path(document.path).name
    plain = text.plain
    if manual:
        m = manual_match(filename, items, manual)
        if m.score >= 1.0:
            idx = manual[re.sub(r"\.[^.]+$", "", filename)] - 1
            from textalchemy.pipeline.signals import DEFAULT_WEIGHTS
            w = {**DEFAULT_WEIGHTS, **(weights or {})}
            m.weight = w.get("manual", 100.0)
            return Match(
                document=document,
                item=items[idx],
                signals=[m],
                matched=True,
            )

    best_item: Optional[BibItem] = None
    best_signals: list = []
    best_score = 0.0
    for item in items:
        signals = collect_signals(
            text=plain, filename=filename, item=item, manual=manual, weights=weights,
        )
        score = sum(s.contribution for s in signals)
        if score > best_score:
            best_score = score
            best_item = item
            best_signals = signals

    return Match(
        document=document,
        item=best_item,
        signals=best_signals,
        matched=best_score >= threshold and best_item is not None,
    )


__all__ = ["match_bibliography"]
