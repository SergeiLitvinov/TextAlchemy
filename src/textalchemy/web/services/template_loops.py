"""Application policy for repeating one paragraph over an array field."""
import hashlib
import json
import keyword
import re
from pathlib import Path

from opendoc_formats.docx import InsertParagraph, SetParagraphText

from textalchemy.web.services.template_layout import compatible_controls
from textalchemy.web.services.template_variables import TOKEN, open_template, rename_patches, save_template_copy

ITEM = '__ta_item'
START = re.compile(r'^\s*{%\s*for\s+__ta_item\s+in\s+([A-Za-z_][A-Za-z0-9_]*)\s*%}\s*$')
END = re.compile(r'^\s*{%\s*endfor\s*%}\s*$')


def _structure(package, schema: dict):
    children, blocks = package.body, []
    _, protected = compatible_controls(package, schema)
    paragraphs = {paragraph.id: paragraph for paragraph in package.paragraphs}
    arrays = {field['name'] for field in schema['fields'] if field['type'] == 'array'}
    index = 0
    while index < len(children):
        node = children[index]
        match = START.fullmatch(node.text) if node.kind == 'paragraph' else None
        field = ''
        if match:
            if (index + 2 >= len(children) or children[index + 1].kind != 'paragraph'
                    or children[index + 2].kind != 'paragraph' or not END.fullmatch(children[index + 2].text)
                    or match[1] not in arrays):
                raise ValueError('Поддерживается только цикл вокруг одного абзаца по полю-списку.')
            field = match[1]
            index += 1
            node = children[index]
        if (node.kind == 'paragraph' and not paragraphs[node.paragraph_id].has_section_break
                and protected.get(node.paragraph_id, 'loop') == 'loop'):
            text = node.text
            variables = sorted({m[1] for m in TOKEN.finditer(text)})
            remainder = TOKEN.sub('', text)
            if variables and not any(marker in remainder for marker in ('{{', '}}', '{%', '%}')):
                blocks.append({'id': index, 'text': text, 'field': field,
                               'variables': [ITEM] if field else [v for v in variables if v != ITEM]})
        index += 2 if field else 1
    return blocks


def inspect_loops(data: bytes, schema: dict) -> dict:
    with open_template(data) as package:
        blocks = _structure(package, schema)
    revision = hashlib.sha256(data + json.dumps(schema, sort_keys=True).encode()).hexdigest()
    return {'blocks': blocks, 'revision': revision}


def loop_schema(schema: dict, field: str) -> dict:
    if (not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', field) or keyword.iskeyword(field)
            or field in {'true', 'false', 'none', 'loop', ITEM, 'self', 'super'}):
        raise ValueError('Введите допустимое имя поля-списка латинскими буквами, цифрами и подчёркиванием.')
    copied = json.loads(json.dumps(schema))
    if any(item['name'] == ITEM for item in copied['fields']):
        raise ValueError('Имя служебной переменной цикла занято в схеме.')
    existing = next((item for item in copied['fields'] if item['name'] == field), None)
    if existing and existing['type'] != 'array':
        raise ValueError('Поле с таким именем уже существует и не является списком.')
    if existing is None:
        copied['fields'].append({'name': field, 'type': 'array', 'default': [], 'required': False,
                                 'description': 'Значения повторяемого содержимого'})
    return copied


def loop_copy(path: Path, schema: dict, *, block: int, variable: str, field: str, revision: str) -> str:
    data = path.read_bytes()
    inspection = inspect_loops(data, schema)
    if revision != inspection['revision']:
        raise ValueError('Шаблон или схема изменились. Загрузите абзацы заново.')
    selected = next((item for item in inspection['blocks'] if item['id'] == block), None)
    if selected is None or variable not in selected['variables']:
        raise ValueError('Выбранный абзац или переменная недоступны')
    copied = loop_schema(schema, field)
    opening = '{% for ' + ITEM + ' in ' + field + ' %}'
    with open_template(data) as package:
        paragraph_id = package.body[block].paragraph_id
        if selected['field']:
            patches = [SetParagraphText(package.body[block - 1].paragraph_id, opening)]
        else:
            paragraph = next(p for p in package.paragraphs if p.id == paragraph_id)
            patches = [*rename_patches(paragraph, variable, ITEM),
                       InsertParagraph(paragraph_id, opening),
                       InsertParagraph(paragraph_id, '{% endfor %}', position='after')]
        updated = package.to_bytes(patches)
    return save_template_copy(updated, copied)
