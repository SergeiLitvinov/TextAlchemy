"""Persistent generator snapshots with transactional revision checks."""
import json
import sqlite3
import uuid
from pathlib import Path

from textalchemy.web.services.ocr_drafts import DraftConflictError


def validate_snapshot(snapshot: dict, schema: dict) -> None:
    if len(json.dumps(snapshot, ensure_ascii=False).encode('utf-8')) > 5 * 1024 * 1024:
        raise ValueError('Набор превышает 5 МБ. Уменьшите изображения или объём данных.')
    if snapshot.get('version') != 1 or snapshot.get('format') not in ('docx', 'html', 'pdf'):
        raise ValueError('Неподдержанный формат набора')
    if json.loads(snapshot.get('schema', 'null')) != schema:
        raise DraftConflictError('Схема шаблона изменилась. Набор сохранён без изменений.')
    values = snapshot.get('values')
    if not isinstance(snapshot.get('output'), str) or not isinstance(values, list) or len(values) != len(schema['fields']):
        raise ValueError('Неверная структура набора')
    for value, field in zip(values, schema['fields'], strict=True):
        expected = bool if field.get('type') == 'boolean' else str
        if not isinstance(value, dict) or value.get('name') != field['name'] or type(value.get('value')) is not expected:
            raise ValueError('Набор не соответствует полям шаблона')


class DatasetStore:
    def __init__(self, root: Path):
        self.path = root / 'generator-datasets.sqlite3'

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('CREATE TABLE IF NOT EXISTS datasets '
                           '(id TEXT PRIMARY KEY, template TEXT, name TEXT, name_key TEXT, revision INTEGER, snapshot TEXT, '
                           'UNIQUE(template, name_key))')
        return connection

    def list(self, template: str) -> list[dict]:
        connection = self._connect()
        try:
            return [dict(row) for row in connection.execute(
                'SELECT id, template, name, revision FROM datasets WHERE template=? ORDER BY name_key', (template,))]
        finally:
            connection.close()

    def get(self, dataset_id: str) -> dict:
        connection = self._connect()
        try:
            row = connection.execute('SELECT * FROM datasets WHERE id=?', (dataset_id,)).fetchone()
            if row is None:
                raise LookupError('Набор не найден')
            result = dict(row)
            result.pop('name_key')
            result['snapshot'] = json.loads(result['snapshot'])
            return result
        finally:
            connection.close()

    def save(self, *, template: str, name: str, snapshot: dict,
             dataset_id: str | None = None, revision: int | None = None) -> dict:
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError('Имя набора должно содержать от 1 до 80 символов')
        connection = self._connect()
        dataset_id = dataset_id or str(uuid.uuid4())
        next_revision = 1 if revision is None else revision + 1
        try:
            with connection:
                if revision is None:
                    connection.execute('INSERT INTO datasets VALUES (?, ?, ?, ?, ?, ?)',
                                       (dataset_id, template, name, name.casefold(), 1, json.dumps(snapshot, ensure_ascii=False)))
                else:
                    changed = connection.execute('UPDATE datasets SET name=?, name_key=?, revision=?, snapshot=? '
                        'WHERE id=? AND template=? AND revision=?',
                        (name, name.casefold(), next_revision, json.dumps(snapshot, ensure_ascii=False),
                         dataset_id, template, revision))
                    if changed.rowcount != 1:
                        raise DraftConflictError('Набор изменён в другой вкладке или недоступен. Загрузите актуальную версию '
                                                 'либо сохраните свои данные под новым именем.')
        except sqlite3.IntegrityError as error:
            raise DraftConflictError(
                'Набор с таким именем уже существует. Выберите другое имя или загрузите его для обновления.'
            ) from error
        finally:
            connection.close()
        return {'id': dataset_id, 'template': template, 'name': name, 'revision': next_revision}
