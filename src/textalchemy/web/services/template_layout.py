"""Validate application control strings over backend-independent document snapshots."""
import re

START = re.compile(r'^\s*{%\s*(if\s+(?:not\s+)?([A-Za-z_]\w*)|for\s+__ta_item\s+in\s+([A-Za-z_]\w*))\s*%}\s*$')


def _ids(item, table):
    return item.paragraph_ids if table else ((item.paragraph_id,) if item.paragraph_id else ())


def _scan(nodes, fields, controls, protected, table=False):
    index = 0
    while index < len(nodes):
        node = nodes[index]
        match = START.fullmatch(node.text)
        if not match:
            index += 1
            continue
        kind, field = ('condition', match[2]) if match[2] else ('loop', match[3])
        end = 'endif' if kind == 'condition' else 'endfor'
        expected = 'boolean' if kind == 'condition' else 'array'
        if (index + 2 >= len(nodes) or fields.get(field) != expected
                or not re.fullmatch(r'\s*{%\s*' + end + r'\s*%}\s*', nodes[index + 2].text)
                or (not table and any(n.kind != 'paragraph' for n in nodes[index:index + 3]))
                or (table and kind != 'loop') or '{%' in nodes[index + 1].text):
            raise ValueError('Поддержаны отдельные условия и циклы одного абзаца или строки без вложенности и else.')
        for marker in (node, nodes[index + 2]):
            controls.update(_ids(marker, table))
        for paragraph_id in _ids(nodes[index + 1], table):
            protected[paragraph_id] = 'row' if table else kind
        index += 3


def compatible_controls(package, schema):
    if any(paragraph.has_nested_paragraphs for paragraph in package.paragraphs):
        raise ValueError('Вложенные текстовые области пока не поддерживаются редактором переменных.')
    controls, protected = set(), {}
    fields = {field['name']: field['type'] for field in schema['fields']}
    _scan(package.body, fields, controls, protected)
    for table in package.tables:
        if table.is_body:
            _scan(table.rows, fields, controls, protected, True)
    for paragraph in package.paragraphs:
        if any(mark in paragraph.text for mark in ('{%', '%}')) and paragraph.id not in controls:
            raise ValueError('Вложенные или неизвестные управляющие конструкции не поддерживаются редактором.')
    return controls, protected
