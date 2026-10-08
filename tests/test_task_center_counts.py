"""Global activity must include older work beyond the recent task list."""

from types import SimpleNamespace

from textalchemy.web.services.task_center import TaskCenterService


def test_global_activity_is_not_limited_to_twelve_recent_finished_tasks():
    records = [{'task_id': f'done-{index}', 'status': 'done'} for index in range(12)]
    records.append({'task_id': 'older-running', 'status': 'running'})
    store = SimpleNamespace(list_tasks=lambda limit: records, ttl_seconds=3600, storage_bytes=lambda: 0)
    snapshot = TaskCenterService(store).snapshot()
    assert len(snapshot['tasks']) == 12
    assert snapshot['tasks'][0]['task_id'] == 'older-running'
    assert all(task['status'] == 'done' for task in snapshot['tasks'][1:])
    assert snapshot['active'] == 1
    assert snapshot['counts'] == {'done': 12, 'running': 1}
