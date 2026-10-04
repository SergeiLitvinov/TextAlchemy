"""Variable policy and immutable template copies, using native library snapshots."""
import hashlib
import json
import re
import uuid
from pathlib import Path

from opendoc_formats.docx import DocxLimits, DocxPackage, ReplaceTextSpan
from opendoc_formats.errors import BackendUnavailableError

from textalchemy.core.exceptions import GenerateError
from textalchemy.web.services.template_layout import compatible_controls

TOKEN = re.compile(r'\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}')


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


def open_template(data: bytes) -> DocxPackage:
    try:
        return DocxPackage(data, limits=DocxLimits(max_uncompressed_bytes=100 * 1024 * 1024))
    except BackendUnavailableError as error:
        raise ValueError('Обработчик DOCX недоступен. Установите приложение с поддержкой DOCX.') from error


def template_paragraphs(package):
    for paragraph in package.paragraphs:
        if paragraph.has_nested_paragraphs:
            raise ValueError('Вложенные текстовые области пока не поддерживаются редактором переменных.')
        if paragraph.runs:
            yield paragraph


def inspect_variables(data: bytes, schema: dict) -> dict:
    variables = {}
    with open_template(data) as package:
        controls, _ = compatible_controls(package, schema)
        for paragraph in template_paragraphs(package):
            if paragraph.id in controls:
                continue
            text = paragraph.text
            helpers = r'{{\s*(?:bibliography|toc)\(\)\s*}}|{{\s*(?:id|ref)\(["\'][\w:-]+["\']\)\s*}}'
            remainder = re.sub(helpers, '', TOKEN.sub('', text))
            if any(marker in remainder for marker in ('{{', '}}', '{%', '%}')):
                raise ValueError('Этот редактор поддерживает только простые переменные без условий, циклов и выражений.')
            for match in TOKEN.finditer(text):
                if match[1] != '__ta_item':
                    variables.setdefault(match[1], []).append(text)
    return {'revision': hashlib.sha256(data + json.dumps(schema, sort_keys=True).encode()).hexdigest(),
            'variables': [{'name': name, 'contexts': contexts} for name, contexts in sorted(variables.items())]}


def rename_patches(paragraph, old: str, new: str):
    return [ReplaceTextSpan(paragraph.id, *match.span(), match[0].replace(old, new, 1))
            for match in TOKEN.finditer(paragraph.text) if match[1] == old]


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
    with open_template(data) as package:
        patches = [patch for paragraph in template_paragraphs(package) for patch in rename_patches(paragraph, old, new)]
        updated = package.to_bytes(patches)
    copied_schema = json.loads(json.dumps(schema))
    for field in copied_schema['fields']:
        if field['name'] == old:
            field['name'] = new
    return save_template_copy(updated, copied_schema)


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
