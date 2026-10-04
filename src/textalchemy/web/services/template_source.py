"""Choose source text and fields; file structure and span edits belong to the library."""

import hashlib
import json
import re
from pathlib import Path

from opendoc_formats.docx import ReplaceTextSpan

from textalchemy.web.services.template_variables import TOKEN, open_template, save_template_copy, template_paragraphs


def checked_docx(data: bytes):
    return open_template(data)


def revision(data, schema):
    return hashlib.sha256(data + json.dumps(schema, sort_keys=True).encode()).hexdigest()


def paragraphs(package):
    return (
        paragraph
        for paragraph in template_paragraphs(package)
        if paragraph.role in {"body", "header", "footer", "footnote", "endnote"}
    )


def inspect_source(data: bytes, schema: dict, query: str = "") -> dict:
    blocks, occurrences, suggestions = [], [], set()
    with checked_docx(data) as package:
        for paragraph in paragraphs(package):
            if len(blocks) >= 2000:
                raise ValueError("Документ содержит больше 2000 текстовых абзацев. Разделите образец на части.")
            key, text = paragraph.id, paragraph.text
            location = "Колонтитул" if paragraph.role in {"header", "footer"} else "Таблица" if paragraph.in_table else "Текст"
            blocks.append({"id": key, "text": text, "location": location})
            suggestions.update(re.findall(r"\b\d{2}\.\d{2}\.\d{4}\b|\b[А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+\b", text))
            if query and not any(mark in query for mark in ("{{", "}}", "{%", "%}")):
                for match in re.finditer(re.escape(query), text):
                    if any(a <= match.start() < b or a < match.end() <= b for a, b in (m.span() for m in TOKEN.finditer(text))):
                        continue
                    occurrences.append(
                        {"id": key, "start": match.start(), "end": match.end(), "text": text, "location": location}
                    )
    return {
        "revision": revision(data, schema),
        "blocks": blocks,
        "occurrences": occurrences,
        "suggestions": sorted(suggestions)[:30],
    }


def field_copy(path: Path, schema: dict, *, query: str, label: str, selected: list, expected: str) -> str:
    data = path.read_bytes()
    inspection = inspect_source(data, schema, query)
    if expected != inspection["revision"]:
        raise ValueError("Образец изменился. Загрузите совпадения заново.")
    if not query or not label.strip() or not selected:
        raise ValueError("Укажите заменяемый текст, название поля и выберите вхождения.")
    choices = {(item["id"], item["start"], item["end"]) for item in inspection["occurrences"]}
    requested = [(item["id"], item["start"], item["end"]) for item in selected]
    if len(set(requested)) != len(requested) or not set(requested) <= choices:
        raise ValueError("Выбранные вхождения недоступны. Обновите поиск.")
    copied = json.loads(json.dumps(schema))
    names = {item["name"] for item in copied["fields"]}
    number = 1
    while f"field_{number}" in names:
        number += 1
    name = f"field_{number}"
    copied["fields"].append({"name": name, "type": "string", "required": True, "default": query, "description": label.strip()})
    patches = [ReplaceTextSpan(key, start, end, "{{ " + name + " }}") for key, start, end in requested]
    with checked_docx(data) as package:
        updated = package.to_bytes(patches)
    return save_template_copy(updated, copied)


def fill_text_package(path: Path, output: Path, values: dict) -> bool:
    """Preserve native package parts for templates containing scalar text fields."""
    with checked_docx(path.read_bytes()) as package:
        patches = []
        for paragraph in paragraphs(package):
            text = paragraph.text
            if any(marker in TOKEN.sub("", text) for marker in ("{{", "}}", "{%", "%}")):
                return False
            if any(not isinstance(values.get(match[1]), (str, int, float, bool)) for match in TOKEN.finditer(text)):
                return False
            patches.extend(ReplaceTextSpan(paragraph.id, *match.span(), str(values[match[1]])) for match in TOKEN.finditer(text))
        package.write(output, patches)
    return True
