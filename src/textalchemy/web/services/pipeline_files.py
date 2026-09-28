"""Web uploads and run outputs, confined to managed workspaces and task TTL."""
import copy
import json
import uuid
from pathlib import Path

from textalchemy.core.registry import get
from textalchemy.pipeline.runner import run_pipeline
from textalchemy.web.workspace import create_web_workspace


def store_input(path: Path) -> dict:
    from textalchemy.web.app import tasks_store

    task_id = uuid.uuid4().hex
    artifact = tasks_store.store_artifact(task_id, path, path.name)
    tasks_store.set(task_id, {'status': 'done', 'queue_kind': 'pipeline-input', 'artifact': artifact})
    return {'value': '@upload:' + task_id, 'name': path.name}


def _resolve_uploads(value):
    from textalchemy.web.app import tasks_store

    if isinstance(value, str) and value.startswith('@upload:'):
        task_id = value.removeprefix('@upload:')
        task = tasks_store.get(task_id)
        path = tasks_store.result_path(task_id, task['artifact']) if task and task.get('queue_kind') == 'pipeline-input' else None
        if path is None:
            raise ValueError('Загруженный файл недоступен или истёк. Выберите его заново.')
        return str(path)
    if isinstance(value, dict):
        return {key: _resolve_uploads(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_uploads(item) for item in value]
    return value


def _prepare_outputs(spec, workspace):
    outputs = []
    for index, step in enumerate(spec.get('steps') or []):
        operation = get(step['op'])
        import inspect

        signature = inspect.signature(operation.func)
        params = step.setdefault('params', {})
        for key in ('output_path', 'output_dir', 'output'):
            if key not in signature.parameters:
                continue
            default = signature.parameters[key].default
            name = params.get(key, default if isinstance(default, str) else 'result')
            if name is None:
                continue
            if not isinstance(name, str) or name.startswith('$') or '{' in name:
                raise ValueError('В Web задайте имя выходного файла напрямую, без ссылки на контекст.')
            filename = f'{index + 1:02d}-' + Path(name.replace('\\', '/')).name
            path = workspace.artifact_path(filename, fallback=f'{index + 1:02d}-result')
            params[key] = str(path)
            outputs.append(path)
    return outputs


def _persist(path, store):
    task_id = uuid.uuid4().hex
    artifact = store.store_artifact(task_id, path, path.name)
    store.set(task_id, {'status': 'done', 'queue_kind': 'pipeline-result', 'artifact': artifact, 'filename': artifact})
    return {'name': artifact, 'url': f'/api/pipeline/results/{task_id}'}


def execute_web_pipeline(spec: dict) -> dict:
    from textalchemy.web.app import tasks_store

    with create_web_workspace() as workspace:
        prepared = _resolve_uploads(copy.deepcopy(spec))
        outputs = _prepare_outputs(prepared, workspace)
        result = run_pipeline(prepared)
        downloads = []
        if result.ok:
            for path in outputs:
                if path.exists():
                    workspace.validate_artifact(path)
                    downloads.append(_persist(path, tasks_store))
            if not downloads and result.final is not None:
                text = result.final if isinstance(result.final, str) else json.dumps(
                    result.to_dict()['final'], ensure_ascii=False, indent=2)
                last_op = result.steps[-1].op if result.steps else ''
                suffix = '.tex' if last_op.startswith('render.latex') else '.txt' if isinstance(result.final, str) else '.json'
                path = workspace.artifact_path('result' + suffix)
                path.write_text(text, encoding='utf-8')
                workspace.validate_artifact(path)
                downloads.append(_persist(path, tasks_store))
        return {'success': True, 'result': result.to_dict(), 'downloads': downloads}


def pipeline_result(task_id):
    from textalchemy.web.app import tasks_store

    task = tasks_store.get(task_id)
    path = tasks_store.result_path(task_id, task['artifact']) if task and task.get('queue_kind') == 'pipeline-result' else None
    if path is None:
        raise LookupError('Результат недоступен или срок хранения истёк. Запустите сценарий заново.')
    return path
