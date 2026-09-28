"""Turn explicitly selected text occurrences in an ordinary DOCX into fields."""
import hashlib
import io
import json
import re
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from textalchemy.web.services.template_variables import TOKEN, W, _paragraphs, _parts, save_template_copy


def checked_docx(data: bytes):
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 3000 or sum(item.file_size for item in infos) > 100 * 1024 * 1024:
                raise ValueError('DOCX слишком велик после распаковки (лимит 100 МБ).')
            if 'word/document.xml' not in archive.namelist():
                raise ValueError('Нужен документ DOCX.')
            if any('vbaProject' in item.filename for item in infos):
                raise ValueError('Документы с макросами не поддерживаются.')
        return dict(_parts(data))
    except (BadZipFile, KeyError, SyntaxError) as error:
        raise ValueError('Не удалось прочитать DOCX.') from error


def revision(data, schema):
    return hashlib.sha256(data + json.dumps(schema, sort_keys=True).encode()).hexdigest()


def paragraphs(parts):
    for part, root in parts.items():
        if not re.fullmatch(r'word/(document|header\d+|footer\d+|footnotes|endnotes)\.xml', part):
            continue
        for index, (nodes, text) in enumerate(_paragraphs(root)):
            yield f'{part}:{index}', nodes, text


def inspect_source(data: bytes, schema: dict, query: str = '') -> dict:
    parts = checked_docx(data)
    blocks, occurrences, suggestions = [], [], set()
    for key, nodes, text in paragraphs(parts):
        if len(blocks) >= 2000:
            raise ValueError('Документ содержит больше 2000 текстовых абзацев. Разделите образец на части.')
        location = 'Колонтитул' if any(v in key for v in ('header', 'footer')) else 'Таблица' if any(
            n.tag == W + 'tc' for n in nodes[0].iterancestors()) else 'Текст'
        blocks.append({'id': key, 'text': text, 'location': location})
        suggestions.update(re.findall(r'\b\d{2}\.\d{2}\.\d{4}\b|\b[А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+\b', text))
        if query and not any(mark in query for mark in ('{{', '}}', '{%', '%}')):
            for match in re.finditer(re.escape(query), text):
                if any(a <= match.start() < b or a < match.end() <= b for a, b in (m.span() for m in TOKEN.finditer(text))):
                    continue
                occurrences.append({'id': key, 'start': match.start(), 'end': match.end(),
                                    'text': text, 'location': location})
    return {'revision': revision(data, schema), 'blocks': blocks, 'occurrences': occurrences,
            'suggestions': sorted(suggestions)[:30]}


def replace_span(nodes, start, end, replacement):
    offset = 0
    for node in nodes:
        text = node.text or ''
        right = offset + len(text)
        if right > start and offset < end:
            node.text = text[:max(0, start - offset)] + (replacement if offset <= start < right else '') + text[end - offset:]
            node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        offset = right


def publish_parts(data, parts, schema):
    from lxml import etree

    output = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as source, ZipFile(output, 'w') as target:
        for info in source.infolist():
            content = etree.tostring(parts[info.filename], xml_declaration=True, encoding='UTF-8', standalone=True
                                    ) if info.filename in parts else source.read(info.filename)
            target.writestr(info, content)
    return save_template_copy(output.getvalue(), schema)


def field_copy(path: Path, schema: dict, *, query: str, label: str, selected: list, expected: str) -> str:
    data = path.read_bytes()
    inspection = inspect_source(data, schema, query)
    if expected != inspection['revision']:
        raise ValueError('Образец изменился. Загрузите совпадения заново.')
    if not query or not label.strip() or not selected:
        raise ValueError('Укажите заменяемый текст, название поля и выберите вхождения.')
    choices = {(item['id'], item['start'], item['end']) for item in inspection['occurrences']}
    requested = [(item['id'], item['start'], item['end']) for item in selected]
    if len(set(requested)) != len(requested) or not set(requested) <= choices:
        raise ValueError('Выбранные вхождения недоступны. Обновите поиск.')
    copied = json.loads(json.dumps(schema))
    names = {item['name'] for item in copied['fields']}
    number = 1
    while f'field_{number}' in names:
        number += 1
    name = f'field_{number}'
    copied['fields'].append({'name': name, 'type': 'string', 'required': True, 'default': query,
                              'description': label.strip()})
    parts = checked_docx(data)
    for key, nodes, _ in paragraphs(parts):
        for _, start, end in sorted((item for item in requested if item[0] == key), reverse=True):
            replace_span(nodes, start, end, '{{ ' + name + ' }}')
    changed = {key.rsplit(':', 1)[0] for key, _, _ in requested}
    return publish_parts(data, {key: value for key, value in parts.items() if key in changed}, copied)


def fill_text_package(path: Path, output: Path, values: dict) -> bool:
    """Preserve the exact package when a template contains only scalar text fields."""
    from lxml import etree

    data = path.read_bytes()
    parts = checked_docx(data)
    for _, _, text in paragraphs(parts):
        if any(marker in TOKEN.sub('', text) for marker in ('{{', '}}', '{%', '%}')):
            return False
        if any(not isinstance(values.get(match[1]), (str, int, float, bool)) for match in TOKEN.finditer(text)):
            return False
    changed = set()
    for key, nodes, text in paragraphs(parts):
        for match in reversed(list(TOKEN.finditer(text))):
            replace_span(nodes, *match.span(), str(values[match[1]]))
            changed.add(key.rsplit(':', 1)[0])
    for part in changed:
        for node in list(parts[part].iter(W + 't')):
            segments = (node.text or '').replace('\r\n', '\n').split('\n')
            if len(segments) < 2:
                continue
            node.text = segments[0]
            tail = node
            for segment in segments[1:]:
                line_break = etree.Element(W + 'br')
                text_node = etree.Element(W + 't')
                text_node.text = segment
                text_node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                tail.addnext(line_break)
                line_break.addnext(text_node)
                tail = text_node
    with ZipFile(io.BytesIO(data)) as source, ZipFile(output, 'w') as target:
        for info in source.infolist():
            content = etree.tostring(parts[info.filename], xml_declaration=True, encoding='UTF-8', standalone=True
                                    ) if info.filename in changed else source.read(info.filename)
            target.writestr(info, content)
    return True
