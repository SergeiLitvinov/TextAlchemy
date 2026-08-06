"""Хранилище фоновых задач с TTL на диске (вместо памяти процесса).

Каждая задача — JSON-файл ``<root>/<task_id>.json`` с метаданными и каталог
``<root>/<task_id>/`` с артефактом результата. Метки времени — wall-clock,
задачи старше ``ttl_seconds`` удаляются лениво при чтении и в ``prune()``.
Такая схема переживает перезапуск сервера и не держит байты результата
в памяти процесса.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Optional

DEFAULT_TASK_TTL_SECONDS = 3600


class TaskStore:
    """Потокобезопасное on-disk хранилище задач с TTL."""

    def __init__(self, root: str | Path, *, ttl_seconds: int = DEFAULT_TASK_TTL_SECONDS) -> None:
        self.root = Path(root)
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()

    def set(self, task_id: str, payload: dict[str, Any]) -> None:
        """Записать/обновить метаданные задачи (и протушить старые)."""
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            self._write_meta_locked(task_id, {**payload, "_ts": time.time()})
            self._prune_locked()

    def get(self, task_id: str) -> Optional[dict[str, Any]]:
        """Вернуть метаданные задачи или ``None`` (в т.ч. если она протухла)."""
        with self._lock:
            meta = self._read_meta_locked(task_id)
            if meta is None:
                return None
            if self._is_stale_locked(meta):
                self._delete_locked(task_id)
                return None
            return meta

    def store_artifact(self, task_id: str, source: Path, filename: str) -> str:
        """Скопировать артефакт в каталог задачи; вернуть сохранённое имя.

        Для каталогов (например, PPTX→HTML) создаётся zip рядом с задачей.
        """
        with self._lock:
            task_dir = self._task_dir(task_id)
            task_dir.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                safe = _safe_filename(filename, fallback="converted")
                zip_path = task_dir / f"{safe}.zip"
                if zip_path.exists():
                    zip_path.unlink()
                shutil.make_archive(str(zip_path.with_suffix("")), "zip", source)
                return zip_path.name
            stored = task_dir / _safe_filename(filename, fallback="converted")
            shutil.copy2(source, stored)
            return stored.name

    def store_source(self, task_id: str, source: Path, filename: str) -> str:
        """Сохранить исходный файл задачи, чтобы её можно было перезапустить."""
        with self._lock:
            task_dir = self._task_dir(task_id)
            task_dir.mkdir(parents=True, exist_ok=True)
            source_dir = task_dir / "source"
            source_dir.mkdir(exist_ok=True)
            stored = source_dir / _safe_filename(filename, fallback="source")
            shutil.copy2(source, stored)
            return stored.name

    def source_path(self, task_id: str) -> Optional[Path]:
        """Путь к сохранённому исходнику задачи (только внутри её каталога)."""
        with self._lock:
            task_dir = self._task_dir(task_id).resolve()
            source_dir = task_dir / "source"
            if not source_dir.is_dir():
                return None
            candidates = sorted(source_dir.iterdir())
            if not candidates:
                return None
            candidate = candidates[0].resolve()
            if not candidate.is_file() or source_dir.resolve() not in candidate.parents:
                return None
            return candidate

    def result_path(self, task_id: str, artifact_name: str) -> Optional[Path]:
        """Путь к артефакту задачи (только внутри её каталога)."""
        with self._lock:
            task_dir = self._task_dir(task_id).resolve()
            candidate = (task_dir / artifact_name).resolve()
            if not candidate.is_file() or task_dir not in candidate.parents:
                return None
            return candidate

    def delete(self, task_id: str) -> None:
        with self._lock:
            self._delete_locked(task_id)

    def set_job(self, job_id: str, payload: dict[str, Any]) -> None:
        """Записать метаданные пакетной задачи (job) и протушить старые."""
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            self._jobs_dir().mkdir(exist_ok=True)
            self._write_job_locked(job_id, {**payload, "_ts": time.time()})
            self._prune_locked()

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """Вернуть метаданные job или ``None`` (в т.ч. если они протухли)."""
        with self._lock:
            path = self._job_path(job_id)
            if not path.is_file():
                return None
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            if not isinstance(payload, dict):
                return None
            if self._is_stale_locked(payload):
                self._delete_job_locked(job_id)
                return None
            return payload

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Список последних jobs, свежие первыми (после ленивой чистки)."""
        with self._lock:
            self._prune_locked()
            jobs_dir = self._jobs_dir()
            if not jobs_dir.is_dir():
                return []
            jobs: list[dict[str, Any]] = []
            for path in sorted(jobs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict):
                    jobs.append(payload)
                if len(jobs) >= limit:
                    break
            return jobs

    def delete_job(self, job_id: str) -> None:
        with self._lock:
            self._delete_job_locked(job_id)

    def prune(self) -> int:
        """Удалить все протухшие задачи и jobs; вернуть число удалённых."""
        with self._lock:
            return self._prune_locked()

    def _task_dir(self, task_id: str) -> Path:
        return self.root / task_id

    def _jobs_dir(self) -> Path:
        return self.root / "jobs"

    def _job_path(self, job_id: str) -> Path:
        return self._jobs_dir() / f"{job_id}.json"

    def _meta_path(self, task_id: str) -> Path:
        return self.root / f"{task_id}.json"

    def _read_meta_locked(self, task_id: str) -> Optional[dict]:
        path = self._meta_path(task_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _write_meta_locked(self, task_id: str, payload: dict) -> None:
        self._meta_path(task_id).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _delete_locked(self, task_id: str) -> None:
        self._meta_path(task_id).unlink(missing_ok=True)
        shutil.rmtree(self._task_dir(task_id), ignore_errors=True)

    def _write_job_locked(self, job_id: str, payload: dict) -> None:
        self._job_path(job_id).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _delete_job_locked(self, job_id: str) -> None:
        self._job_path(job_id).unlink(missing_ok=True)

    def _is_stale_locked(self, meta: dict) -> bool:
        ts = meta.get("_ts", 0)
        return isinstance(ts, (int, float)) and time.time() - ts > self.ttl_seconds

    def _prune_locked(self) -> int:
        if not self.root.is_dir():
            return 0
        now = time.time()
        removed = 0
        for meta_path in self.root.glob("*.json"):
            task_id = meta_path.stem
            try:
                payload = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._delete_locked(task_id)
                removed += 1
                continue
            ts = payload.get("_ts", 0) if isinstance(payload, dict) else 0
            if isinstance(ts, (int, float)) and now - ts > self.ttl_seconds:
                self._delete_locked(task_id)
                removed += 1
        jobs_dir = self._jobs_dir()
        if jobs_dir.is_dir():
            for meta_path in jobs_dir.glob("*.json"):
                job_id = meta_path.stem
                try:
                    payload = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    self._delete_job_locked(job_id)
                    removed += 1
                    continue
                ts = payload.get("_ts", 0) if isinstance(payload, dict) else 0
                if not isinstance(payload, dict) or (isinstance(ts, (int, float)) and now - ts > self.ttl_seconds):
                    self._delete_job_locked(job_id)
                    removed += 1
        return removed


def _safe_filename(name: str, *, fallback: str) -> str:
    normalized = str(name).replace("\\", "/").replace("\x00", "")
    candidate = normalized.rsplit("/", 1)[-1].strip()
    if candidate in {"", ".", ".."}:
        candidate = fallback
    if len(candidate) > 160:
        suffix = Path(candidate).suffix[:20]
        candidate = f"{Path(candidate).stem[: 160 - len(suffix)]}{suffix}"
    return candidate


__all__ = ["DEFAULT_TASK_TTL_SECONDS", "TaskStore"]
