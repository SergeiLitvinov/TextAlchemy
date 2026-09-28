"""Persist one generated file and expose its own page preview until task expiry."""
import uuid
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from textalchemy.generate.template_schema import (
    TemplateSchema,
    TemplateValueType,
    _get_path,
    _set_path,
    validate_template_data,
)
from textalchemy.web.preview import cached_page_count


def prepare_draft_preview(schema: TemplateSchema, params: dict):
    """Fill missing fields visibly without relaxing validation of supplied values."""
    values, fields, missing = deepcopy(params), [], []
    neutral = {TemplateValueType.ARRAY: [], TemplateValueType.OBJECT: {}, TemplateValueType.BOOLEAN: False}
    for field in schema.fields:
        exists, value = _get_path(values, field.name)
        blank = value is None or (isinstance(value, str) and not value.strip())
        if (not exists and not field.has_default) or (exists and blank):
            label = field.description or field.name
            if field.required:
                missing.append({'name': field.name, 'label': label})
            placeholder = f'[Не заполнено: {label}]' if field.required else ''
            _set_path(values, field.name, deepcopy(neutral.get(field.type, placeholder)))
            fields.append(replace(field, type=TemplateValueType.ANY, required=False))
        else:
            fields.append(field)
    draft_schema = TemplateSchema(fields=fields, allow_extra=schema.allow_extra)
    return validate_template_data(draft_schema, values), draft_schema, missing


def store_generated_preview(path: Path, fmt: str) -> dict:
    from textalchemy.web.app import tasks_store

    task_id = uuid.uuid4().hex
    artifact = tasks_store.store_artifact(task_id, path, path.name)
    tasks_store.set(task_id, {'status': 'done', 'artifact': artifact, 'filename': path.name,
                              'queue_kind': 'generate-preview', 'target_format': fmt})
    saved = tasks_store.result_path(task_id, artifact)
    try:
        pages = cached_page_count(tasks_store.preview_dir(task_id), saved, 'result')
    except Exception:  # noqa: BLE001 - the generated file remains downloadable
        pages = 0
    return {'success': True, 'id': task_id, 'pages': pages, 'filename': path.name,
            'available': pages > 0, 'download': f'/api/generate/results/{task_id}'}


def generated_result(task_id: str):
    from textalchemy.web.app import tasks_store

    task = tasks_store.get(task_id)
    if not task or task.get('queue_kind') != 'generate-preview':
        raise LookupError('Результат не найден или срок хранения истёк. Обновите предпросмотр.')
    path = tasks_store.result_path(task_id, task['artifact'])
    if path is None:
        raise LookupError('Файл результата недоступен. Обновите предпросмотр.')
    return task, path, tasks_store.preview_dir(task_id)
