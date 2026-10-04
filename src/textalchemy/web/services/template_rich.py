"""Choose typed content and references; native paragraph edits belong to the library."""

import json
import keyword
import re
from pathlib import Path

from opendoc_formats.docx import SetParagraphText

from textalchemy.web.services.template_layout import compatible_controls
from textalchemy.web.services.template_source import checked_docx, paragraphs, revision
from textalchemy.web.services.template_variables import save_template_copy


def rich_copy(path: Path, schema: dict, *, block: str, kind: str, field: str, expected: str) -> str:
    data = path.read_bytes()
    if revision(data, schema) != expected:
        raise ValueError("Шаблон изменился. Загрузите абзацы заново.")
    with checked_docx(data) as package:
        controls, protected = compatible_controls(package, schema)
        selection = next((p for p in paragraphs(package) if p.id == block), None)
        if not selection or selection.role != "body":
            raise ValueError("Выберите абзац основного документа.")
        text = selection.text
        if block in controls or block in protected or "{{" in text or "{%" in text:
            raise ValueError("Выберите обычный абзац вне условия или цикла.")
        if selection.has_image:
            raise ValueError("Абзац с существующим изображением не заменяется этим действием.")
        if (
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_:-]{0,63}", field)
            or keyword.iskeyword(field)
            or field in {"true", "false", "none", "loop", "self", "super", "toc", "ref", "id"}
        ):
            raise ValueError("Введите имя латинскими буквами, цифрами, подчёркиванием или двоеточием.")
        copied = json.loads(json.dumps(schema))
        kinds = {"image": "image", "formula": "formula", "bibliography": "array"}
        if kind in kinds:
            name = "bibliography" if kind == "bibliography" else field
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name) or any(f["name"] == name for f in copied["fields"]):
                raise ValueError("Нужно новое уникальное имя поля.")
            definition = {
                "name": name,
                "type": kinds[kind],
                "required": True,
                "description": {"image": "Изображение", "formula": "Формула", "bibliography": "Список источников"}[kind],
            }
            if kind == "bibliography":
                definition["default"] = []
            copied["fields"].append(definition)
            replacement = "{{ bibliography() }}" if kind == "bibliography" else "{{ " + name + " }}"
        elif kind in {"id", "ref"}:
            replacement = "{{ " + kind + "(" + json.dumps(field) + ") }}"
            if kind == "id":
                replacement = " " + replacement
        else:
            raise ValueError("Неизвестный тип содержимого.")
        updated = package.to_bytes([SetParagraphText(block, replacement, append=kind == "id")])
    return save_template_copy(updated, copied)
