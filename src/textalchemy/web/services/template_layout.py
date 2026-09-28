"""Validate disjoint simple controls so independent editors can coexist safely."""
import re

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
START = re.compile(r'^\s*{%\s*(if\s+(?:not\s+)?([A-Za-z_]\w*)|for\s+__ta_item\s+in\s+([A-Za-z_]\w*))\s*%}\s*$')


def _text(node):
    return ''.join(item.text or '' for item in node.iter(W + 't'))


def _scan(nodes, fields, controls, protected, table=False):
    index = 0
    while index < len(nodes):
        node = nodes[index]
        match = START.fullmatch(_text(node))
        if not match:
            index += 1
            continue
        kind, field = ('condition', match[2]) if match[2] else ('loop', match[3])
        end = 'endif' if kind == 'condition' else 'endfor'
        expected = 'boolean' if kind == 'condition' else 'array'
        if (index + 2 >= len(nodes) or fields.get(field) != expected
                or not re.fullmatch(r'\s*{%\s*' + end + r'\s*%}\s*', _text(nodes[index + 2]))
                or (not table and any(n.tag != W + 'p' for n in nodes[index:index + 3]))
                or (table and kind != 'loop') or '{%' in _text(nodes[index + 1])):
            raise ValueError('Поддержаны отдельные условия и циклы одного абзаца или строки без вложенности и else.')
        for marker in (node, nodes[index + 2]):
            controls.update(marker.iter(W + 'p'))
        for paragraph in nodes[index + 1].iter(W + 'p'):
            protected[paragraph] = 'row' if table else kind
        index += 3


def compatible_controls(parts, schema):
    controls, protected = set(), {}
    fields = {field['name']: field['type'] for field in schema['fields']}
    body = parts['word/document.xml'].find(W + 'body')
    # A table's joined text is not a paragraph marker.
    _scan(list(body), fields, controls, protected)
    for table in body.findall(W + 'tbl'):
        _scan(table.findall(W + 'tr'), fields, controls, protected, True)
    for root in parts.values():
        for paragraph in root.iter(W + 'p'):
            if any(mark in _text(paragraph) for mark in ('{%', '%}')) and paragraph not in controls:
                raise ValueError('Вложенные или неизвестные управляющие конструкции не поддерживаются редактором.')
    return controls, protected
