"""Сохранённое визуальное свидетельство относится только к измеренному результату."""

from __future__ import annotations

import concurrent.futures
import importlib
from hashlib import sha256

import pytest

from tests import test_web_preview_services as fixtures
from textalchemy.web.services.conversion_preview import ConversionPreviewService, PreviewError
from textalchemy.web.tasks import TaskStore

preview_service = fixtures.preview_service


def test_measurement_survives_restart_without_touching_snapshot_or_ttl(preview_service: ConversionPreviewService) -> None:
    """Настоящий рендер сохраняет условия, отпечатки и область проверки."""
    service = preview_service
    original = service.store.get("example")
    image = service.diff("example", page=2, dpi=72)
    reopened = TaskStore(service.store.root)
    records = reopened.preview_measurements("example", expected=original)
    assert len(records) == 1
    record = records[0]
    assert record["page"] == 2 and record["dpi"] == 72
    assert record["similarity"] == image.similarity and record["rmse"] == image.rmse
    assert record["method"] == "normalised-grayscale-mae-v1" and record["normalization_pixels"] == [160, 160]
    assert record["scope"] == "page_images_only" and record["editability_verified"] is None
    assert set(record["versions"]) == {"textalchemy", "opendoc-model", "opendoc-formats", "pillow"}
    assert all(record["versions"].values()) and record["measured_at"]
    for side in ("source", "target"):
        assert record[f"{side}_png_sha256"] == sha256(service.page("example", side=side, page=2, dpi=72).content).hexdigest()
    assert reopened.get("example") == original == service.store.get("example")


def test_concurrent_pages_and_remeasurement_keep_latest_per_page(preview_service: ConversionPreviewService) -> None:
    """Параллельные сравнения не теряют записи; повтор страницы заменяет её условия."""
    service = preview_service
    original = service.store.get("example")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(service.diff, "example", page=page, dpi=72) for page in (1, 2)]
        for future in futures:
            assert future.result(timeout=20).content.startswith(b"\x89PNG")
    service.diff("example", page=1, dpi=110)
    records = service.store.preview_measurements("example", expected=original)
    assert [(record["page"], record["dpi"]) for record in records] == [(1, 110), (2, 72)]
    assert service.store.get("example") == original


def test_retry_removes_measurements(preview_service: ConversionPreviewService) -> None:
    service = preview_service
    service.diff("example")
    original = service.store.get("example")
    assert service.store.prepare_retry("example", expected=original, updates={"report": None})
    assert not list(service.store.root.glob("example/preview/*/visual-measurements.json"))
    assert service.store.preview_measurements("example", expected=original) == []
    assert service.store.preview_measurements("example", expected=service.store.get("example")) == []


@pytest.mark.parametrize("expire", [False, True])
def test_change_at_commit_never_attaches_old_measurement(
    preview_service: ConversionPreviewService, monkeypatch: pytest.MonkeyPatch, expire: bool
) -> None:
    """Смена результата или истечение TTL непосредственно перед записью отклоняют измерение."""
    service = preview_service
    original = service.store.get("example")
    save = service.store.store_preview_measurement

    def change(task_id: str, **kwargs: object) -> bool:
        if expire:
            module = importlib.import_module("textalchemy.web.tasks")
            monkeypatch.setattr(module.time, "time", lambda: original["_ts"] + service.store.ttl_seconds + 1)
        else:
            service.store.clear_result(task_id)
            service.store.set(task_id, {**original, "revision": 2})
        return save(task_id, **kwargs)

    monkeypatch.setattr(service.store, "store_preview_measurement", change)
    with pytest.raises(PreviewError) as error:
        service.diff("example")
    assert error.value.status_code == (404 if expire else 409)
    assert not list(service.store.root.glob("example/preview/*/visual-measurements.json"))


def test_failed_persistence_does_not_claim_success(
    preview_service: ConversionPreviewService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object, **_kwargs: object) -> bool:
        raise OSError("disk full")

    monkeypatch.setattr(preview_service.store, "store_preview_measurement", fail)
    with pytest.raises(PreviewError, match="сохранить измерение") as error:
        preview_service.diff("example")
    assert error.value.status_code == 503
    assert preview_service.store.preview_measurements("example", expected=preview_service.store.get("example")) == []


def test_corrupt_sidecar_can_be_replaced(preview_service: ConversionPreviewService) -> None:
    original = preview_service.store.get("example")
    directory = preview_service.store.preview_revision_dir("example", expected=original)
    (directory / "visual-measurements.json").write_text('[{}, {"page": "invalid"}]', encoding="utf-8")
    preview_service.diff("example")
    assert len(preview_service.store.preview_measurements("example", expected=original)) == 1
