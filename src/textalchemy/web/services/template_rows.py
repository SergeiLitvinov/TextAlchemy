"""Повторение простой строки таблицы DOCX по списку значений."""
import hashlib
import json
from pathlib import Path

from textalchemy.web.services.template_conditions import _control, _text
from textalchemy.web.services.template_layout import compatible_controls
from textalchemy.web.services.template_loops import END, ITEM, START, loop_schema, publish_loop
from textalchemy.web.services.template_variables import TOKEN, W, _paragraphs, _parts, _rename_nodes


def _marker(row, pattern):
    cells = row.findall(W + 'tc')
    if len(cells) != 1 or len(cells[0].findall(W + 'p')) != 1:
        return None
    return pattern.fullmatch(_text(row))


def _simple(row, columns):
    return (len(row.findall(W + 'tc')) == columns and columns > 0
            and all(row.find('.//' + W + tag) is None for tag in ('gridSpan', 'vMerge', 'hMerge', 'tbl', 'sectPr')))


def _table_blocks(table, table_index, arrays, allowed):
    rows, blocks, index = table.findall(W + 'tr'), [], 0
    columns = len(table.findall('./' + W + 'tblGrid/' + W + 'gridCol'))
    while index < len(rows):
        row, field = rows[index], ''
        match = _marker(row, START)
        if match:
            if index + 2 >= len(rows) or not _marker(rows[index + 2], END) or match[1] not in arrays:
                raise ValueError('Поддерживается цикл одной строки без вложенности.')
            allowed.update((rows[index].find('.//' + W + 'p'), rows[index + 2].find('.//' + W + 'p')))
            field = match[1]
            index += 1
            row = rows[index]
        if _simple(row, columns):
            texts = [_text(cell) for cell in row.findall(W + 'tc')]
            variables = sorted({match[1] for text in texts for match in TOKEN.finditer(text)})
            if variables and all(not any(mark in TOKEN.sub('', text) for mark in ('{{', '}}', '{%', '%}')) for text in texts):
                blocks.append({'id': f'{table_index}:{index}', 'text': ' | '.join(texts), 'field': field,
                               'variables': [ITEM] if field else [v for v in variables if v != ITEM]})
        index += 2 if field else 1
    return blocks


def _structure(data, schema):
    parts = dict(_parts(data))
    root = parts['word/document.xml']
    tables = root.find(W + 'body').findall(W + 'tbl')
    arrays = {field['name'] for field in schema['fields'] if field['type'] == 'array'}
    allowed, blocks = set(), []
    compatible, _ = compatible_controls(parts, schema)
    allowed.update(compatible)
    for index, table in enumerate(tables):
        blocks.extend(_table_blocks(table, index, arrays, allowed))
    for part in parts.values():
        for nodes, text in _paragraphs(part):
            paragraph = next(nodes[0].iterancestors(W + 'p'))
            if ('{%' in text or '%}' in text) and paragraph not in allowed:
                raise ValueError('Условия, циклы абзацев и вложенные конструкции этим редактором не поддерживаются.')
    revision = hashlib.sha256(data + json.dumps(schema, sort_keys=True).encode()).hexdigest()
    return root, tables, blocks, revision


def inspect_rows(data: bytes, schema: dict) -> dict:
    _, _, blocks, revision = _structure(data, schema)
    return {'blocks': blocks, 'revision': revision}


def _control_row(text, columns):
    from lxml import etree

    row = etree.Element(W + 'tr')
    cell = etree.SubElement(row, W + 'tc')
    props = etree.SubElement(cell, W + 'tcPr')
    etree.SubElement(props, W + 'gridSpan').set(W + 'val', str(columns))
    cell.append(_control(text))
    return row


def row_copy(path: Path, schema: dict, *, block: str, variable: str, field: str, revision: str) -> str:
    data = path.read_bytes()
    root, tables, blocks, current = _structure(data, schema)
    if revision != current:
        raise ValueError('Шаблон или схема изменились. Загрузите строки заново.')
    selected = next((item for item in blocks if item['id'] == block), None)
    if selected is None or variable not in selected['variables']:
        raise ValueError('Выбранная строка или переменная недоступны; объединённые ячейки не поддерживаются.')
    copied = loop_schema(schema, field)
    table_index, row_index = map(int, block.split(':'))
    table = tables[table_index]
    row = table.findall(W + 'tr')[row_index]
    opening = _control_row('{% for ' + ITEM + ' in ' + field + ' %}', len(row.findall(W + 'tc')))
    if selected['field']:
        table.replace(table.findall(W + 'tr')[row_index - 1], opening)
    else:
        for nodes, text in _paragraphs(row):
            _rename_nodes(nodes, text, variable, ITEM)
        row.addprevious(opening)
        row.addnext(_control_row('{% endfor %}', len(row.findall(W + 'tc'))))
    return publish_loop(data, root, copied)
