"""Choose repeatable table rows; native row editing belongs to OpenDoc Formats."""
import hashlib
import json
from pathlib import Path

from opendoc_formats.docx import InsertTableRow, SetTableRowText

from textalchemy.web.services.template_layout import compatible_controls
from textalchemy.web.services.template_loops import END, ITEM, START, loop_schema
from textalchemy.web.services.template_variables import TOKEN, open_template, rename_patches, save_template_copy


def _marker(row, pattern):
    if len(row.cells) != 1 or len(row.cells[0].paragraph_ids) != 1:
        return None
    return pattern.fullmatch(row.text)


def _table_blocks(table, table_index, arrays):
    rows, blocks, index = table.rows, [], 0
    while index < len(rows):
        row, field = rows[index], ''
        match = _marker(row, START)
        if match:
            if index + 2 >= len(rows) or not _marker(rows[index + 2], END) or match[1] not in arrays:
                raise ValueError('Поддерживается цикл одной строки без вложенности.')
            field = match[1]
            index += 1
            row = rows[index]
        if row.simple:
            texts = [cell.text for cell in row.cells]
            variables = sorted({match[1] for text in texts for match in TOKEN.finditer(text)})
            if variables and all(not any(mark in TOKEN.sub('', text) for mark in ('{{', '}}', '{%', '%}')) for text in texts):
                blocks.append({'id': f'{table_index}:{index}', 'text': ' | '.join(texts), 'field': field,
                               'variables': [ITEM] if field else [v for v in variables if v != ITEM]})
        index += 2 if field else 1
    return blocks


def inspect_rows(data: bytes, schema: dict) -> dict:
    arrays = {field['name'] for field in schema['fields'] if field['type'] == 'array'}
    with open_template(data) as package:
        compatible_controls(package, schema)
        blocks = [block for index, table in enumerate(table for table in package.tables if table.is_body)
                  for block in _table_blocks(table, index, arrays)]
    revision = hashlib.sha256(data + json.dumps(schema, sort_keys=True).encode()).hexdigest()
    return {'blocks': blocks, 'revision': revision}


def row_copy(path: Path, schema: dict, *, block: str, variable: str, field: str, revision: str) -> str:
    data = path.read_bytes()
    inspection = inspect_rows(data, schema)
    if revision != inspection['revision']:
        raise ValueError('Шаблон или схема изменились. Загрузите строки заново.')
    selected = next((item for item in inspection['blocks'] if item['id'] == block), None)
    if selected is None or variable not in selected['variables']:
        raise ValueError('Выбранная строка или переменная недоступны; объединённые ячейки не поддерживаются.')
    copied = loop_schema(schema, field)
    table_index, row_index = map(int, block.split(':'))
    opening = '{% for ' + ITEM + ' in ' + field + ' %}'
    with open_template(data) as package:
        table = [table for table in package.tables if table.is_body][table_index]
        row = table.rows[row_index]
        if selected['field']:
            patches = [SetTableRowText(table.rows[row_index - 1].id, opening)]
        else:
            paragraphs = {p.id: p for p in package.paragraphs}
            patches = [patch for paragraph_id in row.paragraph_ids
                       for patch in rename_patches(paragraphs[paragraph_id], variable, ITEM)]
            patches.extend([InsertTableRow(row.id, opening),
                            InsertTableRow(row.id, '{% endfor %}', position='after')])
        updated = package.to_bytes(patches)
    return save_template_copy(updated, copied)
