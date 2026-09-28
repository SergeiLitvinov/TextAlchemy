"""Сохранение исправленного OCR-текста в модели документа и экспорт её версии."""

from __future__ import annotations

import re
import threading
import uuid
from typing import Any

from textalchemy.core.document_codec import document_from_dict, document_to_dict
from textalchemy.core.document_model import DocumentModel, Paragraph, Section, TextRun
from textalchemy.web.tasks import TaskStore
from textalchemy.web.workspace import create_web_workspace

MAX_TEXT_LENGTH = 1_000_000
_edit_lock = threading.Lock()


class DraftConflictError(ValueError):
    """Сохранённая версия изменилась в другом запросе."""


def draft_store(parent: TaskStore) -> TaskStore:
    return TaskStore(parent.root / "ocr-drafts", ttl_seconds=parent.ttl_seconds)


def _model(text: str, source_name: str) -> dict[str, Any]:
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError("Текст превышает лимит в 1 000 000 символов")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", text):
        raise ValueError("Текст содержит недопустимые служебные символы")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return document_to_dict(DocumentModel(
        source_format="txt",
        sections=[Section(blocks=[Paragraph(content=[TextRun(line)]) for line in text.split("\n")])],
        metadata={"source_name": source_name, "origin": "ocr-text", "scope": "plain-text"},
    ))


def get_draft(store: TaskStore, draft_id: str) -> dict[str, Any]:
    with _edit_lock:
        value = store.get(draft_id)
    if value is None:
        raise LookupError("Текст не найден или срок хранения истёк. Распознайте файл заново.")
    return _snapshot(value, draft_id)


def _snapshot(value: dict[str, Any], draft_id: str) -> dict[str, Any]:
    document = document_from_dict(value["model"])
    text = "\n".join(block.plain_text for section in document.sections for block in section.blocks)
    return {"revision": value["revision"], "source_name": value["source_name"],
            "model": value["model"], "draft_id": draft_id, "text": text}


def create_draft(store: TaskStore, *, text: str, source_name: str) -> dict[str, Any]:
    draft_id = str(uuid.uuid4())
    model = _model(text, source_name)
    value = {"revision": 1, "model": model, "source_name": source_name}
    with _edit_lock:
        store.set(draft_id, value)
    return _snapshot(value, draft_id)


def save_draft(store: TaskStore, draft_id: str, *, text: str, revision: int) -> dict[str, Any]:
    with _edit_lock:
        current = store.get(draft_id)
        if current is None:
            raise LookupError("Текст не найден или срок хранения истёк. Распознайте файл заново.")
        if current["revision"] != revision:
            raise DraftConflictError("Текст изменён в другой вкладке. Скопируйте свои правки и загрузите сохранённую версию.")
        model = _model(text, current["source_name"])
        value = {**current, "revision": revision + 1, "model": model}
        store.set(draft_id, value)
    return _snapshot(value, draft_id)


def export_draft(store: TaskStore, draft_id: str, *, revision: int, format: str) -> bytes:
    if format not in {"txt", "docx", "pdf", "model"}:
        raise ValueError("Выберите TXT, DOCX, PDF или JSON-модель")
    value = get_draft(store, draft_id)
    if value["revision"] != revision:
        raise DraftConflictError("Сохранённая версия изменилась. Загрузите её перед скачиванием.")
    document = document_from_dict(value["model"])
    if format == "model":
        import json

        return json.dumps(value["model"], ensure_ascii=False, indent=2).encode("utf-8")
    with create_web_workspace() as workspace:
        output = workspace.artifact_path(f"corrected.{format}")
        if format == "txt":
            from textalchemy.convert.txt_writer import write_txt_model

            report = write_txt_model(document, output)
        elif format == "docx":
            from textalchemy.convert.docx_writer import write_docx_model

            report = write_docx_model(document, output)
        elif format == "pdf":
            from textalchemy.convert.pdf_writer import write_pdf_model

            report = write_pdf_model(document, output)
        else:
            raise ValueError("Выберите TXT, DOCX, PDF или JSON-модель")
        if not report.success:
            raise ValueError("Не удалось экспортировать текст. Сохранённые правки доступны для повторной попытки.")
        workspace.validate_artifact(output)
        return output.read_bytes()
