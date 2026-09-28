"""Conservative variable rename in DOCX, preserving package parts and run styles."""
import hashlib
import io
import json
import re
import uuid
from pathlib import Path
from zipfile import ZipFile

from textalchemy.core.exceptions import GenerateError
from textalchemy.web.services.template_layout import compatible_controls

TOKEN = re.compile(r'\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}')
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def custom_root() -> Path:
    from textalchemy.web.app import data_dir

    return data_dir / 'edited-templates'


def custom_path(name: str) -> Path:
    if not re.fullmatch(r'edited-[0-9a-f]{32}', name):
        raise GenerateError('Неверное имя копии шаблона')
    path = custom_root() / name / 'template.docx'
    if not path.is_file():
        raise GenerateError('Копия шаблона не найдена')
    return path


def custom_templates() -> list[dict]:
    return [{'name': path.parent.name, 'description': 'Изменённый шаблон · ' + path.parent.name[-8:], 'template_type': 'docx'}
            for path in sorted(custom_root().glob('edited-*/template.docx'))]


def _parts(data: bytes):
    from lxml import etree

    with ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if name.startswith('word/') and name.endswith('.xml'):
                root = etree.fromstring(archive.read(name), parser=etree.XMLParser(resolve_entities=False, no_network=True))
                yield name, root


def _paragraphs(root):
    for paragraph in root.iter(W + 'p'):
        if any(True for _ in paragraph.iterdescendants(W + 'p')):
            raise ValueError('Вложенные текстовые области пока не поддерживаются редактором переменных.')
        nodes = list(paragraph.iter(W + 't'))
        if nodes:
            yield nodes, ''.join(node.text or '' for node in nodes)


def inspect_variables(data: bytes, schema: dict) -> dict:
    variables = {}
    parts = dict(_parts(data))
    controls, _ = compatible_controls(parts, schema)
    for root in parts.values():
        for nodes, text in _paragraphs(root):
            if next(nodes[0].iterancestors(W + 'p')) in controls:
                continue
            helpers = r'{{\s*(?:bibliography|toc)\(\)\s*}}|{{\s*(?:id|ref)\([\"\'][\w:-]+[\"\']\)\s*}}'
            remainder = re.sub(helpers, '', TOKEN.sub('', text))
            if any(marker in remainder for marker in ('{{', '}}', '{%', '%}')):
                raise ValueError('Этот редактор поддерживает только простые переменные без условий, циклов и выражений.')
            for match in TOKEN.finditer(text):
                if match[1] == '__ta_item':
                    continue
                variables.setdefault(match[1], []).append(text)
    return {'revision': hashlib.sha256(data + json.dumps(schema, sort_keys=True).encode()).hexdigest(),
            'variables': [{'name': name, 'contexts': contexts} for name, contexts in sorted(variables.items())]}


def _rename_nodes(nodes, text: str, old: str, new: str):
    spans, offset = [], 0
    for node in nodes:
        end = offset + len(node.text or '')
        spans.append((node, offset, end))
        offset = end
    for match in reversed(list(TOKEN.finditer(text))):
        if match[1] != old:
            continue
        # Keep the complete placeholder in its first run: the model renderer
        # evaluates runs separately. Surrounding text retains its own runs.
        start, end = match.span()
        replacement = match[0].replace(old, new, 1)
        for node, left, right in spans:
            if right <= start or left >= end:
                continue
            value = node.text or ''
            node.text = value[:max(0, start - left)] + (replacement if left <= start < right else '') + value[end - left:]
            node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')


def rename_copy(path: Path, schema: dict, *, old: str, new: str, revision: str) -> str:
    data = path.read_bytes()
    inspection = inspect_variables(data, schema)
    if revision != inspection['revision']:
        raise ValueError('Шаблон или схема изменились. Загрузите список переменных заново.')
    names = {item['name'] for item in inspection['variables']}
    fields = {item['name'] for item in schema['fields']}
    if old not in names or old not in fields:
        raise ValueError('Переменная отсутствует в шаблоне или схеме')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', new) or new in names | fields:
        raise ValueError('Нужно новое уникальное имя: латинские буквы, цифры и подчёркивание; первая — буква или подчёркивание.')
    from lxml import etree

    updated = {}
    for name, root in _parts(data):
        changed = False
        for nodes, text in _paragraphs(root):
            if any(match[1] == old for match in TOKEN.finditer(text)):
                _rename_nodes(nodes, text, old, new)
                changed = True
        if changed:
            updated[name] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    output = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as source, ZipFile(output, 'w') as target:
        for info in source.infolist():
            target.writestr(info, updated.get(info.filename, source.read(info.filename)))
    copied_schema = json.loads(json.dumps(schema))
    for field in copied_schema['fields']:
        if field['name'] == old:
            field['name'] = new
    return save_template_copy(output.getvalue(), copied_schema)


def save_template_copy(data: bytes, schema: dict) -> str:
    """Publish document and schema together, using an independent immutable name."""
    name = 'edited-' + uuid.uuid4().hex
    root = custom_root()
    root.mkdir(parents=True, exist_ok=True)
    staging = root / ('.' + name)
    staging.mkdir()
    try:
        (staging / 'template.docx').write_bytes(data)
        (staging / 'template.schema.json').write_text(json.dumps(schema, ensure_ascii=False), encoding='utf-8')
        staging.rename(root / name)
    finally:
        if staging.exists():
            for child in staging.iterdir():
                child.unlink()
            staging.rmdir()
    return name
