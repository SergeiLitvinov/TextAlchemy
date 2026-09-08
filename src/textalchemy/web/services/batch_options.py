"""Строгий разбор индивидуальных форматов и приоритетов файлов пакета."""

from __future__ import annotations

import json
from dataclasses import dataclass

from textalchemy.core.document_model import ConversionMode
from textalchemy.core.types import DocFormat


@dataclass(frozen=True)
class BatchFileOptions:
    target: str
    mode: ConversionMode


def parse_batch_options(value: str, count: int, *, target: str, mode: ConversionMode) -> list[BatchFileOptions]:
    if not value:
        return [BatchFileOptions(target, mode) for _ in range(count)]
    try:
        items = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("Индивидуальные настройки должны быть JSON-массивом") from error
    if not isinstance(items, list) or len(items) != count:
        raise ValueError("Число индивидуальных настроек должно совпадать с числом файлов")
    result = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict) or set(item) - {"target_format", "mode"}:
            raise ValueError(f"Файл {index}: допустимы только target_format и mode")
        file_target, file_mode = item.get("target_format", target), item.get("mode", mode.value)
        if not isinstance(file_target, str) or not isinstance(file_mode, str):
            raise ValueError(f"Файл {index}: формат и приоритет должны быть строками")
        if file_target:
            DocFormat(file_target)
        result.append(BatchFileOptions(file_target, ConversionMode(file_mode)))
    return result
