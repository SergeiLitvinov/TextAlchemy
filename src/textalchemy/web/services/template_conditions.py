"""Application policy for a boolean condition around one document paragraph."""
import hashlib
import json
import keyword
import re
from pathlib import Path

from opendoc_formats.docx import InsertParagraph, SetParagraphText

from textalchemy.web.services.template_layout import compatible_controls
from textalchemy.web.services.template_variables import open_template, save_template_copy

IF = re.compile(r'^\s*{%\s*if\s+(not\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*%}\s*$')
END = re.compile(r'^\s*{%\s*endif\s*%}\s*$')


def _structure(package, schema: dict):
    children, blocks = package.body, []
    compatible, protected = compatible_controls(package, schema)
    boolean_fields = {field['name'] for field in schema['fields'] if field['type'] == 'boolean'}
    index = 0
    while index < len(children):
        node = children[index]
        match = IF.fullmatch(node.text) if node.kind == 'paragraph' else None
        if match:
            if (index + 2 >= len(children) or children[index + 1].kind != 'paragraph'
                    or children[index + 2].kind != 'paragraph' or not END.fullmatch(children[index + 2].text)
                    or match[2] not in boolean_fields):
                raise ValueError('Поддерживается только условие по boolean-полю вокруг одного абзаца без else и вложенности.')
            blocks.append({'id': index + 1, 'text': children[index + 1].text, 'field': match[2], 'negate': bool(match[1])})
            index += 3
            continue
        if node.kind == 'paragraph' and node.text.strip() and node.paragraph_id not in compatible | protected.keys():
            blocks.append({'id': index, 'text': node.text, 'field': '', 'negate': False})
        index += 1
    return blocks


def inspect_conditions(data: bytes, schema: dict) -> dict:
    with open_template(data) as package:
        blocks = _structure(package, schema)
    revision = hashlib.sha256(data + json.dumps(schema, sort_keys=True).encode()).hexdigest()
    return {'blocks': blocks, 'revision': revision}


def condition_copy(path: Path, schema: dict, *, block: int, field: str, negate: bool, revision: str) -> str:
    data = path.read_bytes()
    inspected = inspect_conditions(data, schema)
    if revision != inspected['revision']:
        raise ValueError('Шаблон или схема изменились. Загрузите абзацы заново.')
    selected = next((item for item in inspected['blocks'] if item['id'] == block), None)
    if selected is None:
        raise ValueError('Выбранный абзац недоступен')
    if (not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', field) or keyword.iskeyword(field)
            or field in {'true', 'false', 'none', 'loop'}):
        raise ValueError('Введите имя поля латинскими буквами, цифрами и подчёркиванием, начиная с буквы или подчёркивания.')
    copied = json.loads(json.dumps(schema))
    existing = next((item for item in copied['fields'] if item['name'] == field), None)
    if existing and existing['type'] != 'boolean':
        raise ValueError('Поле с таким именем уже существует и не является флажком.')
    if existing is None:
        copied['fields'].append({'name': field, 'type': 'boolean', 'default': False, 'required': False,
                                 'description': 'Показывать выбранный абзац'})
    opening = '{% if ' + ('not ' if negate else '') + field + ' %}'
    with open_template(data) as package:
        paragraph_id = package.body[block].paragraph_id
        if selected['field']:
            patches = [SetParagraphText(package.body[block - 1].paragraph_id, opening)]
        else:
            patches = [InsertParagraph(paragraph_id, opening),
                       InsertParagraph(paragraph_id, '{% endif %}', position='after')]
        updated = package.to_bytes(patches)
    return save_template_copy(updated, copied)
