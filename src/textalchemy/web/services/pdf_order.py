"""Versioned PDF block ordering; stored block payloads are never reconstructed."""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from textalchemy.core.document_codec import document_from_dict, document_to_dict
from textalchemy.core.types import Document
from textalchemy.web.services.ocr_drafts import DraftConflictError
from textalchemy.web.services.pdf_classification import apply_classifications, describe
from textalchemy.web.services.pdf_diagnostics import attach_targets
from textalchemy.web.services.pdf_table_bounds import apply_table_ranges, describe_table
from textalchemy.web.tasks import TaskStore
from textalchemy.web.workspace import create_web_workspace

_lock = threading.Lock()


def store_for(parent: TaskStore) -> TaskStore:
    return TaskStore(parent.root / "pdf-order", ttl_seconds=parent.ttl_seconds)


def load(store: TaskStore, draft_id: str) -> dict:
    with _lock:
        value = store.get(draft_id)
    if value is None:
        raise LookupError("Документ не найден или срок хранения истёк. Загрузите PDF заново.")
    return value


def create(store: TaskStore, path: Path, name: str) -> dict:
    from opendoc_formats.pdf import PdfDocument

    from textalchemy.pipeline.extract import extract_pdf_model

    if path.suffix.lower() != ".pdf":
        raise ValueError("Выберите PDF с текстовым слоем")
    try:
        with PdfDocument(path):
            pass
    except ValueError as error:
        raise ValueError("Не удалось прочитать PDF. Нужен PDF без защиты паролем.") from error
    model = extract_pdf_model(doc=Document.from_path(path), mode="fast")
    if not model.sections:
        raise ValueError("Не удалось прочитать страницы PDF")
    draft_id = str(uuid.uuid4())
    value = {"draft_id": draft_id, "revision": 1, "source_name": name, "model": document_to_dict(model),
             "order": [[str(uuid.uuid4()) for _ in s.blocks] for s in model.sections]}
    with _lock:
        store.store_source(draft_id, path, "source.pdf")
        store.set(draft_id, value)
    return summary(value)


def summary(value: dict) -> dict:
    model = document_from_dict(value["model"])
    pages = []
    for index, section in enumerate(model.sections):
        blocks = []
        for block_id, block in zip(value["order"][index], section.blocks, strict=True):
            label = getattr(block, "plain_text", "") or {"Table": "Таблица", "Image": "Изображение",
                                                        "Formula": "Формула"}.get(type(block).__name__, "Объект")
            box = block.box
            if box is None:
                box = next((item.box for item in getattr(block, "content", []) if getattr(item, "box", None)), None)
            region = None if box is None else [100 * box.x / section.page.width.pt, 100 * box.y / section.page.height.pt,
                                               100 * box.width / section.page.width.pt, 100 * box.height / section.page.height.pt]
            blocks.append({"id": block_id, "label": label[:240], "kind": type(block).__name__,
                           "region": region, **describe(block)})
        raw_blocks = value["model"]["document"]["sections"][index]["blocks"]
        for entry, raw in zip(blocks, raw_blocks, strict=True):
            original = value.get("table_originals", {}).get(entry["id"], raw)
            table = describe_table(original)
            if table:
                table["range"] = value.get("table_ranges", {}).get(entry["id"], [1, table["rows"], 1, table["columns"]])
            entry["table"] = table
        pages.append({"blocks": blocks, "width": section.page.width.pt, "height": section.page.height.pt})
    return {key: value[key] for key in ("draft_id", "revision", "source_name")} | {
        "pages": pages, "warnings": model.metadata.get("warnings", [])}


def reorder(store: TaskStore, draft_id: str, revision: int, order: list[list[str]],
            classifications: dict[str, str] | None = None, table_ranges: dict[str, list[int]] | None = None) -> dict:
    with _lock:
        value = store.get(draft_id)
        if value is None:
            raise LookupError("Документ не найден или срок хранения истёк")
        if value["revision"] != revision:
            raise DraftConflictError(
                "Документ изменён в другой вкладке. Ваш выбор остаётся на экране; загрузите актуальную версию."
            )
        previous = value["order"]
        if len(order) != len(previous) or any(
            len(new) != len(old) or len(set(new)) != len(new) or set(new) != set(old)
            for new, old in zip(order, previous, strict=True)
        ):
            raise ValueError("Порядок должен содержать каждый блок своей страницы ровно один раз")
        sections = value["model"]["document"]["sections"]
        apply_classifications(value, classifications or {})
        apply_table_ranges(value, table_ranges or {})
        for section, old, new in zip(sections, previous, order, strict=True):
            blocks = dict(zip(old, section["blocks"], strict=True))
            section["blocks"] = [blocks[block_id] for block_id in new]
        value.update(order=order, revision=revision + 1)
        store.set(draft_id, value)
    return summary(value)


def page_image(store: TaskStore, draft_id: str, page: int) -> bytes:
    from opendoc_formats.pdf import PdfDocument

    value = load(store, draft_id)
    if not 0 <= page < len(value["order"]):
        raise LookupError("Страница не найдена")
    path = store.source_path(draft_id)
    if path is None:
        raise LookupError("Исходный PDF недоступен")
    with PdfDocument(path) as pdf:
        return pdf.render_page(page, scale=1.5, max_dimension=1400).png


def export(store: TaskStore, draft_id: str, revision: int, format: str) -> bytes:
    value = load(store, draft_id)
    if value["revision"] != revision:
        raise DraftConflictError("Сохранённая версия изменилась. Загрузите её перед скачиванием.")
    if format == "model":
        return json.dumps(value["model"], ensure_ascii=False).encode("utf-8")
    if format != "docx":
        raise ValueError("Выберите DOCX или JSON-модель")
    content, report = _render_docx(value)
    if not report.success:
        raise ValueError("Экспорт не удался. Сохранённый порядок доступен для повторной попытки.")
    return content


def diagnostics(store: TaskStore, draft_id: str, revision: int) -> dict:
    value = load(store, draft_id)
    if value["revision"] != revision:
        raise DraftConflictError("Сохранённая версия изменилась. Загрузите её перед проверкой.")
    _, report = _render_docx(value)
    return attach_targets(value, report.to_dict())


def _render_docx(value: dict):
    from textalchemy.convert.docx_writer import write_docx_model

    with create_web_workspace() as workspace:
        output = workspace.artifact_path("ordered.docx")
        report = write_docx_model(document_from_dict(value["model"]), output)
        if not report.success:
            return b"", report
        workspace.validate_artifact(output)
        return output.read_bytes(), report
