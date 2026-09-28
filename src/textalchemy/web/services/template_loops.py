"""Редактор повторения одного абзаца по списку значений."""
import hashlib
import io
import json
import keyword
import re
from pathlib import Path
from zipfile import ZipFile

from textalchemy.web.services.template_conditions import _control, _text
from textalchemy.web.services.template_layout import compatible_controls
from textalchemy.web.services.template_variables import TOKEN, W, _paragraphs, _parts, _rename_nodes, save_template_copy

ITEM = '__ta_item'
START = re.compile(r'^\s*{%\s*for\s+__ta_item\s+in\s+([A-Za-z_][A-Za-z0-9_]*)\s*%}\s*$')
END = re.compile(r'^\s*{%\s*endfor\s*%}\s*$')


def _structure(data: bytes, schema: dict):
    parts = dict(_parts(data))
    root = parts['word/document.xml']
    body = root.find(W + 'body')
    children, blocks, allowed = list(body), [], set()
    compatible, protected = compatible_controls(parts, schema)
    allowed.update(compatible)
    arrays = {field['name'] for field in schema['fields'] if field['type'] == 'array'}
    index = 0
    while index < len(children):
        node = children[index]
        match = START.fullmatch(_text(node)) if node.tag == W + 'p' else None
        field = ''
        if match:
            if (index + 2 >= len(children) or children[index + 1].tag != W + 'p'
                    or children[index + 2].tag != W + 'p' or not END.fullmatch(_text(children[index + 2]))
                    or match[1] not in arrays):
                raise ValueError('Поддерживается только цикл вокруг одного абзаца по полю-списку.')
            allowed.update((node, children[index + 2]))
            field = match[1]
            index += 1
            node = children[index]
        if (node.tag == W + 'p' and node.find('.//' + W + 'sectPr') is None
                and protected.get(node, 'loop') == 'loop'):
            text = _text(node)
            variables = sorted({m[1] for m in TOKEN.finditer(text)})
            remainder = TOKEN.sub('', text)
            if variables and not any(marker in remainder for marker in ('{{', '}}', '{%', '%}')):
                blocks.append({'id': index, 'text': text, 'field': field,
                               'variables': [ITEM] if field else [v for v in variables if v != ITEM]})
        index += 2 if field else 1
    for part in parts.values():
        for nodes, text in _paragraphs(part):
            paragraph = next(nodes[0].iterancestors(W + 'p'))
            if ('{%' in text or '%}' in text) and paragraph not in allowed:
                raise ValueError('Условия, вложенные циклы и управляющие строки вне основного текста пока не поддерживаются.')
    revision = hashlib.sha256(data + json.dumps(schema, sort_keys=True).encode()).hexdigest()
    return root, body, blocks, revision


def inspect_loops(data: bytes, schema: dict) -> dict:
    _, _, blocks, revision = _structure(data, schema)
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


def publish_loop(data: bytes, root, schema: dict) -> str:
    from lxml import etree

    updated = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    output = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as source, ZipFile(output, 'w') as target:
        for info in source.infolist():
            target.writestr(info, updated if info.filename == 'word/document.xml' else source.read(info.filename))
    return save_template_copy(output.getvalue(), schema)


def loop_copy(path: Path, schema: dict, *, block: int, variable: str, field: str, revision: str) -> str:
    data = path.read_bytes()
    root, body, blocks, current = _structure(data, schema)
    if revision != current:
        raise ValueError('Шаблон или схема изменились. Загрузите абзацы заново.')
    selected = next((item for item in blocks if item['id'] == block), None)
    if selected is None or variable not in selected['variables']:
        raise ValueError('Выбранный абзац или переменная недоступны')
    copied = loop_schema(schema, field)
    paragraph = body[block]
    opening = _control('{% for ' + ITEM + ' in ' + field + ' %}')
    if selected['field']:
        body.replace(body[block - 1], opening)
    else:
        nodes = list(paragraph.iter(W + 't'))
        _rename_nodes(nodes, _text(paragraph), variable, ITEM)
        paragraph.addprevious(opening)
        paragraph.addnext(_control('{% endfor %}'))
    return publish_loop(data, root, copied)
