"""In-process очередь фоновых задач Web-приложения.

Задачи выполняются воркером вне event loop; метаданные и артефакты живут в
``TaskStore`` на диске. При старте приложения задачи, оставшиеся в статусе
``running`` после рестарта, помечаются ``interrupted``.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)

INTERRUPTED_STATUS = "interrupted"
INTERRUPTED_MESSAGE = "Задача прервана перезапуском сервера"
MAX_WORKERS = 2


class TaskQueue:
    """Потокобезопасная очередь синхронных задач с ожиданием простоя."""

    def __init__(self, max_workers: int = MAX_WORKERS) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="textalchemy-task")
        self._lock = threading.Lock()
        self._pending = 0
        self._idle = threading.Event()
        self._idle.set()
        self._futures: dict[str, Future[None]] = {}

    def submit(self, fn: Callable[..., None], *args: Any, **kwargs: Any) -> Future[None]:
        """Поставить задачу на выполнение (не блокирует вызывающий код)."""
        with self._lock:
            self._pending += 1
            self._idle.clear()
        try:
            return self._executor.submit(self._invoke, fn, args, kwargs)
        except Exception:
            # ``ThreadPoolExecutor`` rejects work after shutdown. Do not leave
            # waiters blocked forever with a phantom pending task.
            with self._lock:
                self._pending -= 1
                if self._pending == 0:
                    self._idle.set()
            raise

    def submit_named(self, task_id: str, fn: Callable[..., None], *args: Any, **kwargs: Any) -> Future[None]:
        """Поставить адресуемую задачу, которую можно снять до начала выполнения."""
        future = self.submit(fn, *args, **kwargs)
        with self._lock:
            self._futures[task_id] = future
        future.add_done_callback(lambda completed: self._forget(task_id, completed))
        return future

    def cancel(self, task_id: str) -> bool:
        """Снять ожидающую задачу; выполняющаяся отменяется кооперативно use-case-слоем."""
        with self._lock:
            future = self._futures.get(task_id)
        return bool(future and future.cancel())

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Дождаться завершения всех поставленных задач; True, если успели."""
        return self._idle.wait(timeout)

    def pending(self) -> int:
        with self._lock:
            return self._pending

    def shutdown(self, *, wait: bool = False) -> None:
        # Let queued wrappers run their ``finally`` blocks so ``pending`` and
        # ``wait_idle`` remain truthful during graceful shutdown.
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _invoke(self, fn: Callable[..., None], args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        try:
            fn(*args, **kwargs)
        except Exception:  # noqa: BLE001 - воркер не должен падать из-за одной задачи
            logger.exception("background task raised an unhandled error")
        finally:
            with self._lock:
                self._pending -= 1
                if self._pending == 0:
                    self._idle.set()

    def _forget(self, task_id: str, future: Future[None]) -> None:
        with self._lock:
            if self._futures.get(task_id) is future:
                self._futures.pop(task_id, None)
            if future.cancelled():
                self._pending -= 1
                if self._pending == 0:
                    self._idle.set()


task_queue = TaskQueue()


@dataclass(frozen=True)
class RecoverySummary:
    """Результат восстановления сохранённой очереди при старте."""

    resumed: int = 0
    interrupted: int = 0


def recover_persisted_tasks(
    tasks_store: Any,
    handlers: Mapping[str, Callable[[str], None]],
) -> RecoverySummary:
    """Повторно поставить сохранённые задачи; неизвестные пометить прерванными."""
    resumed = 0
    interrupted = 0
    for task in tasks_store.list_tasks(limit=None):
        task_id = task.pop("task_id", None)
        if task_id is None or task.get("status") not in {"queued", "running"}:
            continue
        handler = handlers.get(str(task.get("queue_kind") or ""))
        if handler is not None:
            try:
                handler(task_id)
                resumed += 1
                continue
            except Exception:  # noqa: BLE001 - invalid persisted jobs must not break application startup
                logger.exception("failed to resume persisted task %s", task_id)
        tasks_store.set(task_id, {**task, "status": INTERRUPTED_STATUS, "error": INTERRUPTED_MESSAGE, "report": None})
        interrupted += 1
    return RecoverySummary(resumed=resumed, interrupted=interrupted)


def recover_interrupted_tasks(tasks_store: Any) -> int:
    """Compatibility helper: mark every unfinished task as interrupted."""
    return recover_persisted_tasks(tasks_store, {}).interrupted


__all__ = [
    "INTERRUPTED_MESSAGE",
    "INTERRUPTED_STATUS",
    "MAX_WORKERS",
    "RecoverySummary",
    "TaskQueue",
    "recover_interrupted_tasks",
    "recover_persisted_tasks",
    "task_queue",
]
