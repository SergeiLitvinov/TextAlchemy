"""Insert typed content and references into explicitly selected simple paragraphs."""
import json
import keyword
import re
from pathlib import Path

from textalchemy.web.services.template_layout import compatible_controls
from textalchemy.web.services.template_source import checked_docx, paragraphs, publish_parts, revision
from textalchemy.web.services.template_variables import W


def rich_copy(path: Path, schema: dict, *, block: str, kind: str, field: str, expected: str) -> str:
    from lxml import etree

    data = path.read_bytes()
    if revision(data, schema) != expected:
        raise ValueError('Шаблон изменился. Загрузите абзацы заново.')
    parts = checked_docx(data)
    controls, protected = compatible_controls(parts, schema)
    selection = next((item for item in paragraphs(parts) if item[0] == block), None)
    if not selection or not block.startswith('word/document.xml:'):
        raise ValueError('Выберите абзац основного документа.')
    _, nodes, text = selection
    paragraph = next(nodes[0].iterancestors(W + 'p'))
    if paragraph in controls or paragraph in protected or '{{' in text or '{%' in text:
        raise ValueError('Выберите обычный абзац вне условия или цикла.')
    if paragraph.find('.//' + W + 'drawing') is not None:
        raise ValueError('Абзац с существующим изображением не заменяется этим действием.')
    if (not re.fullmatch(r'[A-Za-z][A-Za-z0-9_:-]{0,63}', field) or keyword.iskeyword(field)
            or field in {'true', 'false', 'none', 'loop', 'self', 'super', 'toc', 'ref', 'id'}):
        raise ValueError('Введите имя латинскими буквами, цифрами, подчёркиванием или двоеточием.')
    copied = json.loads(json.dumps(schema))
    kinds = {'image': 'image', 'formula': 'formula', 'bibliography': 'array'}
    if kind in kinds:
        name = 'bibliography' if kind == 'bibliography' else field
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', name) or any(f['name'] == name for f in copied['fields']):
            raise ValueError('Нужно новое уникальное имя поля.')
        definition = {'name': name, 'type': kinds[kind], 'required': True,
                      'description': {'image': 'Изображение', 'formula': 'Формула', 'bibliography': 'Список источников'}[kind]}
        if kind == 'bibliography':
            definition['default'] = []
        copied['fields'].append(definition)
        replacement = '{{ bibliography() }}' if kind == 'bibliography' else '{{ ' + name + ' }}'
    elif kind in {'id', 'ref'}:
        replacement = '{{ ' + kind + '(' + json.dumps(field) + ') }}'
        if kind == 'id':
            replacement = ' ' + replacement
    else:
        raise ValueError('Неизвестный тип содержимого.')
    # Keep paragraph properties; replacement gets the original first run style.
    first_run = next(nodes[0].iterancestors(W + 'r'))
    style = first_run.find(W + 'rPr')
    import copy

    saved_style = copy.deepcopy(style) if style is not None else None
    if kind != 'id':
        for child in list(paragraph):
            if child.tag != W + 'pPr':
                paragraph.remove(child)
    run = etree.SubElement(paragraph, W + 'r')
    if saved_style is not None:
        run.append(saved_style)
    etree.SubElement(run, W + 't').text = replacement
    return publish_parts(data, {'word/document.xml': parts['word/document.xml']}, copied)
