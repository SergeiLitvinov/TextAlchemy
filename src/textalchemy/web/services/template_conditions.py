"""Single-paragraph boolean conditions, without nested control-flow editing."""
import hashlib
import io
import json
import keyword
import re
from pathlib import Path
from zipfile import ZipFile

from textalchemy.web.services.template_layout import compatible_controls
from textalchemy.web.services.template_variables import W, _paragraphs, _parts, save_template_copy

IF = re.compile(r'^\s*{%\s*if\s+(not\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*%}\s*$')
END = re.compile(r'^\s*{%\s*endif\s*%}\s*$')


def _text(node):
    return ''.join(item.text or '' for item in node.iter(W + 't'))


def _structure(data: bytes, schema: dict):
    parts = dict(_parts(data))
    root = parts['word/document.xml']
    body = root.find(W + 'body')
    children, blocks, allowed = list(body), [], set()
    compatible, protected = compatible_controls(parts, schema)
    allowed.update(compatible)
    boolean_fields = {field['name'] for field in schema['fields'] if field['type'] == 'boolean'}
    index = 0
    while index < len(children):
        node = children[index]
        text = _text(node)
        match = IF.fullmatch(text) if node.tag == W + 'p' else None
        if match:
            if (index + 2 >= len(children) or children[index + 1].tag != W + 'p'
                    or children[index + 2].tag != W + 'p' or not END.fullmatch(_text(children[index + 2]))
                    or match[2] not in boolean_fields):
                raise ValueError('Поддерживается только условие по boolean-полю вокруг одного абзаца без else и вложенности.')
            allowed.update((node, children[index + 2]))
            blocks.append({'id': index + 1, 'text': _text(children[index + 1]), 'field': match[2], 'negate': bool(match[1])})
            index += 3
            continue
        if node.tag == W + 'p' and text.strip() and node not in compatible and node not in protected:
            blocks.append({'id': index, 'text': text, 'field': '', 'negate': False})
        index += 1
    # Reject directives elsewhere, including tables, headers and nested textboxes.
    for part in parts.values():
        for nodes, text in _paragraphs(part):
            paragraph = next(nodes[0].iterancestors(W + 'p'))
            if ('{%' in text or '%}' in text) and paragraph not in allowed:
                raise ValueError('Циклы, сложные условия и управляющие строки вне основного текста пока не поддерживаются.')
    revision = hashlib.sha256(data + json.dumps(schema, sort_keys=True).encode()).hexdigest()
    return root, body, blocks, revision


def inspect_conditions(data: bytes, schema: dict) -> dict:
    _, _, blocks, revision = _structure(data, schema)
    return {'blocks': blocks, 'revision': revision}


def _control(text: str):
    from lxml import etree

    paragraph = etree.Element(W + 'p')
    etree.SubElement(etree.SubElement(paragraph, W + 'r'), W + 't').text = text
    return paragraph


def condition_copy(path: Path, schema: dict, *, block: int, field: str, negate: bool, revision: str) -> str:
    from lxml import etree

    data = path.read_bytes()
    root, body, blocks, current = _structure(data, schema)
    if revision != current:
        raise ValueError('Шаблон или схема изменились. Загрузите абзацы заново.')
    selected = next((item for item in blocks if item['id'] == block), None)
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
    paragraph = body[block]
    opening = _control('{% if ' + ('not ' if negate else '') + field + ' %}')
    if selected['field']:
        body.replace(body[block - 1], opening)
    else:
        paragraph.addprevious(opening)
        paragraph.addnext(_control('{% endif %}'))
    updated = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    output = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as source, ZipFile(output, 'w') as target:
        for info in source.infolist():
            target.writestr(info, updated if info.filename == 'word/document.xml' else source.read(info.filename))
    return save_template_copy(output.getvalue(), copied)
