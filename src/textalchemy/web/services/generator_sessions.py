"""Загрузка и сохранение наборов генератора с проверкой схемы и ревизии."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from textalchemy.generate.template_schema import TemplateSchema
from textalchemy.web.services.generator_datasets import DatasetStore, validate_snapshot


@dataclass
class GeneratorDatasetService:
    """Прикладной сценарий наборов; схема берётся из текущего каталога шаблонов."""

    store: DatasetStore
    schema_provider: Callable[[str], tuple[TemplateSchema, str]]

    def list(self, template: str) -> list[dict[str, Any]]:
        return self.store.list(template)

    def get(self, dataset_id: str) -> dict[str, Any]:
        result = self.store.get(dataset_id)
        self._validate(result["template"], result["snapshot"])
        return result

    def _validate(self, template: str, snapshot: dict[str, Any]) -> None:
        schema, _ = self.schema_provider(template)
        validate_snapshot(snapshot, schema.to_dict())

    def save(
        self, *, template: str, name: str, snapshot: dict[str, Any], dataset_id: str | None = None, revision: int | None = None
    ) -> dict[str, Any]:
        """Сохранить набор; несовместимая схема или отсутствующая ревизия не изменяют хранилище."""
        if dataset_id is None and revision is not None:
            raise ValueError("Новый набор не должен иметь ревизию")
        if dataset_id is not None and revision is None:
            raise ValueError("Для обновления нужна ревизия загруженного набора")
        self._validate(template, snapshot)
        return self.store.save(template=template, name=name, snapshot=snapshot, dataset_id=dataset_id, revision=revision)
