"""Подготовка снимка изображений для переносимого HTML до записи результата."""

from __future__ import annotations

import base64
import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

from textalchemy.convert.stages import StageContext, StageKind, StageResult, StageValue
from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import Block, DocumentModel, Image, Paragraph, Resource, Table

IMAGE_MEDIA_TYPE = re.compile(r"^image/[a-zA-Z0-9.+-]+$")


def _images(blocks: list[Block], location: str) -> Iterator[tuple[Image, str]]:
    for index, block in enumerate(blocks):
        path = f"{location}[{index}]"
        if isinstance(block, Image):
            yield block, path
        elif isinstance(block, Paragraph):
            for offset, item in enumerate(block.content):
                if isinstance(item, Image):
                    yield item, f"{path}.content[{offset}]"
        elif isinstance(block, Table):
            for row_index, row in enumerate(block.rows):
                for cell_index, cell in enumerate(row.cells):
                    yield from _images(cell.blocks, f"{path}.rows[{row_index}].cells[{cell_index}].blocks")


@dataclass(frozen=True)
class HtmlResourceStage:
    """Прочитать каждый используемый ресурс один раз, сохранив исходную модель."""

    id: str = "html.resources"
    kind: StageKind = StageKind.RESOURCES

    def execute(self, value: StageValue, context: StageContext) -> StageResult:
        if not isinstance(value, DocumentModel):
            raise TypeError("HTML resources stage requires DocumentModel")
        report = ConversionReport(context.output_path)
        resources = dict(value.resources)
        seen: set[str] = set()
        resolved = 0
        byte_count = 0
        references = 0
        for image, location in document_images(value):
            if context.cancelled():
                report.add(IssueSeverity.ERROR, "cancelled", "Resource preparation cancelled")
                return StageResult(value, report)
            references += 1
            key = image.resource_id
            if key in seen:
                continue
            seen.add(key)
            resource = resources.get(key)
            try:
                if resource is None:
                    raise ValueError(f"resource {key!r} not found")
                if not IMAGE_MEDIA_TYPE.fullmatch(resource.media_type):
                    raise ValueError(f"resource {key!r} is not an image ({resource.media_type})")
                if resource.data is not None:
                    raw = resource.data
                elif resource.source is not None:
                    raw = Path(resource.source).read_bytes()
                else:
                    raise ValueError(f"resource {key!r} has no content")
                resources[key] = replace(resource, data=raw)
                resolved += 1
                byte_count += len(raw)
            except (OSError, ValueError) as error:
                report.add(IssueSeverity.ERROR, "image", str(error), location)
        report.metrics["resource_preparation"] = {
            "stage": self.id,
            "references": references,
            "requested": len(seen),
            "resolved": resolved,
            "bytes": byte_count,
            "accepted": report.success,
        }
        return StageResult(replace(value, resources=resources), report)


def document_images(document: DocumentModel) -> Iterator[tuple[Image, str]]:
    """Изображения в отображаемых блоках и колонтитулах, включая таблицы."""
    for section_index, section in enumerate(document.sections):
        for name in ("blocks", "headers", "footers"):
            yield from _images(getattr(section, name), f"sections[{section_index}].{name}")


def image_data_uri(resource: Resource) -> str:
    """Сериализовать подготовленный ресурс без повторного чтения исходного файла."""
    if resource.data is None:
        raise ValueError(f"resource {resource.id!r} was not prepared")
    encoded = base64.b64encode(resource.data).decode("ascii")
    return f"data:{resource.media_type};base64,{encoded}"
