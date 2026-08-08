"""События прогресса для длительных операций (pipeline run, пакетная обработка).

Единый контракт: функции-исполнители принимают необязательный callback
``progress: Callable[[ProgressEvent], None]`` и рассылают события по мере
выполнения. Потребители (CLI, Web, тесты) подписываются независимо от того,
кто и как выполняет работу.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal

ProgressKind = Literal["pipeline_start", "step_start", "step_done", "step_failed", "pipeline_done"]


@dataclass(frozen=True)
class ProgressEvent:
    """Одно событие прогресса."""

    kind: ProgressKind
    index: int
    total: int
    op: str = ""
    name: str = ""
    error: str = ""
    elapsed: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ProgressSink = Callable[[ProgressEvent], None]

__all__ = ["ProgressEvent", "ProgressSink", "ProgressKind"]
