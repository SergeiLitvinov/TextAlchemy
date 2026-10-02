"""Нормализация ссылок и закладок модели для HTML без изменения источника."""

from __future__ import annotations

from dataclasses import dataclass, replace
from urllib.parse import quote

from textalchemy.convert.stages import StageContext, StageKind, StageResult, StageValue
from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import DocumentModel, Paragraph, Table, TextRun


class _NormalizeCancelledError(Exception):
    pass


@dataclass(frozen=True)
class HtmlNormalizeStage:
    """Подготовить HTML-представление Word bookmarks и fragment-ссылок."""

    id: str = "html.normalize"
    kind: StageKind = StageKind.NORMALIZE

    def execute(self, value: StageValue, context: StageContext) -> StageResult:
        if not isinstance(value, DocumentModel):
            raise TypeError("HTML normalization requires DocumentModel")
        report = ConversionReport(context.output_path)
        counts = {"word_bookmarks": 0, "word_internal_links": 0, "inline_anchors": 0}

        def run(item, location):
            if context.cancelled():
                raise _NormalizeCancelledError
            anchor = item.properties.get("anchor_id")
            bookmark = item.properties.get("bookmark_start")
            if isinstance(bookmark, dict):
                name = bookmark.get("name")
                if isinstance(name, str) and name:
                    anchor = name
                    counts["word_bookmarks"] += 1
                else:
                    report.add(IssueSeverity.LOSS, "bookmark", "Word bookmark has no name", location)
            link = item.link
            native_anchor = item.properties.get("hyperlink_anchor")
            if not link and isinstance(native_anchor, str) and native_anchor:
                link = "#" + quote(native_anchor, safe="")
                counts["word_internal_links"] += 1
            counts["inline_anchors"] += bool(anchor)
            prepared = {"anchor_id": str(anchor) if anchor else None, "link": link}
            return replace(item, properties={**item.properties, "html_normalize": prepared})

        def blocks(items, location):
            result = []
            for index, node in enumerate(items):
                path = f"{location}[{index}]"
                if isinstance(node, Paragraph):
                    node = replace(
                        node,
                        content=[
                            run(item, f"{path}.content[{offset}]") if isinstance(item, TextRun) else item
                            for offset, item in enumerate(node.content)
                        ],
                    )
                elif isinstance(node, Table):
                    node = replace(
                        node,
                        rows=[
                            replace(
                                row,
                                cells=[
                                    replace(
                                        cell,
                                        blocks=blocks(
                                            cell.blocks,
                                            f"{path}.rows[{row_index}].cells[{cell_index}].blocks",
                                        ),
                                    )
                                    for cell_index, cell in enumerate(row.cells)
                                ],
                            )
                            for row_index, row in enumerate(node.rows)
                        ],
                    )
                result.append(node)
            return result

        try:
            if context.cancelled():
                raise _NormalizeCancelledError
            sections = [
                replace(
                    section,
                    **{
                        name: blocks(getattr(section, name), f"sections[{index}].{name}")
                        for name in ("blocks", "headers", "footers")
                    },
                )
                for index, section in enumerate(value.sections)
            ]
        except _NormalizeCancelledError:
            report.add(IssueSeverity.ERROR, "cancelled", "HTML normalization cancelled")
            return StageResult(value, report)
        report.metrics["html_normalization"] = {"stage": self.id, **counts}
        return StageResult(replace(value, sections=sections), report)
