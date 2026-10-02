"""Одиночный запуск без HTTP, общие ограничения и сохранность при отказах."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from tests.test_web_batch_services import services as services
from tests.test_web_ingest_services import BytesUpload
from textalchemy.web.services.conversion_submission import (
    ConversionRequestError,
    ConversionSettings,
    ConversionSubmissionService,
    SubmissionUnavailableError,
)
from textalchemy.web.tasks import TaskStore


def single(services: tuple) -> ConversionSubmissionService:
    store, batch, tasks, _queue = services
    return ConversionSubmissionService(store, tasks.persist, tasks.resume, workspace_factory=batch.workspace_factory)


@pytest.mark.parametrize("target,mode", [("html", "balanced"), ("model", "editable")])
def test_real_single_conversion_preserves_source_and_result(services: tuple, target: str, mode: str) -> None:
    store, _batch, _tasks, queue = services
    settings = ConversionSettings(target_format=target, mode=mode, require_unchanged_text=target == "model")
    created = asyncio.run(single(services).submit(BytesUpload("Отчёт.txt", b"Scientific report"), settings=settings))
    assert queue.wait_idle(timeout=30)
    task = store.get(created["task_id"])
    assert task["status"] == "done", task
    assert task["target_format"] == target and task["mode"] == mode
    assert task["require_unchanged_text"] == (target == "model")
    assert store.source_path(created["task_id"]).read_bytes() == b"Scientific report"
    assert "Scientific report" in store.result_path(created["task_id"], task["artifact"]).read_text(encoding="utf-8")
    assert store.list_jobs() == []


@pytest.mark.parametrize(
    "settings",
    [
        ConversionSettings(mode="invalid"),
        ConversionSettings(max_text_edits=-1),
        ConversionSettings(max_changed_formulas=-1),
        ConversionSettings(max_changed_emphasis=-1),
        ConversionSettings(text_preservation="invalid"),
    ],
)
def test_invalid_settings_are_rejected_by_single_and_batch_before_saving(services: tuple, settings: ConversionSettings) -> None:
    store, batch, _tasks, _queue = services
    settings = replace(settings, target_format="model")
    for submit in (
        lambda: single(services).submit(BytesUpload("source.txt", b"source"), settings=settings),
        lambda: batch.submit([BytesUpload("source.txt", b"source")], settings=settings),
    ):
        with pytest.raises(ConversionRequestError) as error:
            asyncio.run(submit())
        assert error.value.status_code == 400
        assert store.list_tasks() == [] and store.list_jobs() == []


def test_partial_single_persistence_rolls_back_only_new_task(services: tuple) -> None:
    store, _batch, tasks, _queue = services
    store.set("old", {"status": "done", "content": "keep"})
    launched = []

    def fail(*args: Any) -> None:
        tasks.persist(*args)
        raise OSError("failed after writing source")

    service = replace(single(services), persist=fail, resume=launched.append)
    with pytest.raises(SubmissionUnavailableError) as error:
        asyncio.run(service.submit(BytesUpload("source.txt", b"source"), settings=ConversionSettings(target_format="model")))
    assert error.value.task_id is None and launched == []
    assert [task["task_id"] for task in store.list_tasks()] == ["old"]
    assert store.get("old")["content"] == "keep"


@pytest.mark.parametrize("note_failure", [False, True])
def test_queue_failure_keeps_durable_source_for_new_store_and_recovery(
    services: tuple, monkeypatch: pytest.MonkeyPatch, note_failure: bool
) -> None:
    store, _batch, tasks, queue = services

    def unavailable(_task_id: str) -> None:
        raise RuntimeError("queue stopped")

    if note_failure:

        def fail_note(*_args: Any) -> None:
            raise OSError("metadata note unavailable")

        monkeypatch.setattr(store, "note_queue_failure", fail_note)
    service = replace(single(services), resume=unavailable)
    with pytest.raises(SubmissionUnavailableError) as error:
        asyncio.run(service.submit(BytesUpload("source.txt", b"Recover me"), settings=ConversionSettings(target_format="model")))
    task_id = error.value.task_id
    reopened = TaskStore(store.root)
    assert reopened.get(task_id)["status"] == "queued"
    assert reopened.source_path(task_id).read_bytes() == b"Recover me"
    tasks.resume(task_id)
    assert queue.wait_idle(timeout=30)
    assert reopened.get(task_id)["status"] == "done"


def test_partial_upload_does_not_save_or_enqueue(services: tuple) -> None:
    class BrokenUpload(BytesUpload):
        async def read(self, size: int = -1) -> bytes:
            if self.offset:
                raise OSError("upload failed")
            return await super().read(size)

    store = services[0]
    with pytest.raises(OSError, match="upload failed"):
        asyncio.run(
            single(services).submit(BrokenUpload("source.txt", b"partial"), settings=ConversionSettings(target_format="model"))
        )
    assert store.list_tasks() == []
