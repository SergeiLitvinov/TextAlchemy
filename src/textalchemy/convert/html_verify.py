"""Проверка внутренних ссылок сериализованного HTML перед публикацией."""

from __future__ import annotations

import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

from textalchemy.convert.stages import StageContext, StageKind, StageResult, StageValue
from textalchemy.core.diagnostics import ConversionReport, IssueSeverity


class _NavigationParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids: Counter[str] = Counter()
        self.links: list[tuple[str, int]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids[attributes["id"]] += 1
        href = attributes.get("href")
        if tag == "a" and href and href.startswith("#") and len(href) > 1:
            self.links.append((unquote(href[1:]), self.getpos()[0]))

    handle_startendtag = handle_starttag


@dataclass(frozen=True)
class HtmlVerifyStage:
    """Проверить существование и однозначность целей fragment-ссылок."""

    id: str = "html.verify"
    kind: StageKind = StageKind.VERIFY

    def execute(self, value: StageValue, context: StageContext) -> StageResult:
        if not isinstance(value, Path):
            raise TypeError("HTML verification requires a serialized Path")
        report = ConversionReport(context.output_path)
        if context.cancelled():
            report.add(IssueSeverity.ERROR, "cancelled", "HTML verification cancelled")
            return StageResult(value, report)
        parser = _NavigationParser()
        try:
            parser.feed(value.read_text(encoding="utf-8"))
            parser.close()
        except (OSError, UnicodeError) as error:
            report.add(IssueSeverity.ERROR, "html-verify", str(error))
            return StageResult(value, report)
        missing = ambiguous = 0
        for target, line in parser.links:
            count = parser.ids[target]
            if count == 1 or (count == 0 and target.lower() == "top"):
                continue
            missing += count == 0
            ambiguous += count > 1
            reason = "missing" if count == 0 else "ambiguous"
            report.add(IssueSeverity.LOSS, "hyperlink", f"Internal link target {target!r} is {reason}", f"html:line[{line}]")
        report.metrics["html_navigation"] = {
            "stage": self.id,
            "internal_links": len(parser.links),
            "missing_targets": missing,
            "ambiguous_targets": ambiguous,
            "duplicate_ids": sum(count > 1 for count in parser.ids.values()),
            "verified": missing == 0 and ambiguous == 0,
        }
        return StageResult(value, report)


def publish_verified_html(html: str, output: Path, report: ConversionReport) -> None:
    """Проверить временный файл и атомарно заменить результат при отсутствии ошибок."""
    with tempfile.TemporaryDirectory(prefix=".textalchemy-html-", dir=output.parent) as directory:
        candidate = Path(directory) / "document.html"
        candidate.write_text(html, encoding="utf-8")
        verified = HtmlVerifyStage().execute(candidate, StageContext(output))
        report.issues.extend(verified.report.issues)
        report.metrics.update(verified.report.metrics)
        if report.success:
            os.replace(candidate, output)
