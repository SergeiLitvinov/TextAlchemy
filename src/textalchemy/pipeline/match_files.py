"""Батч-матчинг: директория + bibfile → список Match с переименованием.

Конечная операция, которой удобно пользоваться в CLI и в pipeline.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional, Union

from textalchemy.core.registry import operation
from textalchemy.core.types import BibItem, DocFormat, Document, Match

logger = logging.getLogger(__name__)


@operation(
    "match.files",
    input_type="path",
    output_type="list[Match]",
    input_param="source",
    description="Сопоставить все файлы в директории со списком BibItem. Возвращает Match[].",
    tags=["match", "batch"],
)
def match_files(
    *,
    source: Union[str, Path],
    items: list[BibItem],
    threshold: float = 0.30,
    manual: Optional[dict[str, int]] = None,
    weights: Optional[dict[str, float]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    copy: bool = True,
    ext_map: Optional[set[str]] = None,
) -> list[Match]:
    """Для каждого файла в ``source`` (включая подпапки) — вычислить Match.

    Если ``output_dir`` задан и ``copy=True`` — копировать файл с новым именем
    (через ``pipeline.name.name_from_match``).

    Возвращает список Match (matched и unmatched — оба).
    """
    from textalchemy.pipeline.match import match_bibliography
    from textalchemy.pipeline.name import name_from_match

    source = Path(source)
    if not source.is_dir():
        raise NotADirectoryError(source)

    extensions = ext_map or {".pdf", ".docx", ".djvu", ".txt"}
    files = [f for f in source.rglob("*") if f.is_file() and f.suffix.lower() in extensions]

    if output_dir is not None and copy:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

    results: list[Match] = []
    for f in files:
        try:
            from textalchemy.pipeline.extract import extract_text
            from textalchemy.pipeline.ingest import ingest_file

            doc = ingest_file(path=f)
            text = extract_text(doc=doc)
            m = match_bibliography(
                text=text, document=doc, items=items,
                threshold=threshold, manual=manual, weights=weights,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("match failed for %s: %s", f, e)
            m = Match(
                document=Document(path=f, format=DocFormat.UNKNOWN,
                                  size=f.stat().st_size, sha256=""),
                item=None,
                matched=False,
            )

        results.append(m)

        if output_dir is not None and copy and m.matched:
            new_name = name_from_match(match=m, ext=f.suffix.lower())
            if new_name:
                target = Path(output_dir) / new_name
                try:
                    shutil.copy2(f, target)
                except Exception as e:  # noqa: BLE001
                    logger.warning("copy failed %s -> %s: %s", f, target, e)

    return results


__all__ = ["match_files"]
