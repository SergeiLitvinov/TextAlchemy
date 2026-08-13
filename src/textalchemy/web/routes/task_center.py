"""Thin HTTP adapter for the global task center."""

from __future__ import annotations

from fastapi import HTTPException

import textalchemy.web.app as web_app
from textalchemy.web.services.task_center import TaskCenterService


def _service() -> TaskCenterService:
    tasks = web_app.conversion_task_service()
    return TaskCenterService(web_app.tasks_store, cancel_task=tasks.cancel, rerun_task=tasks.rerun)


@web_app.app.get("/api/tasks")
async def api_tasks():
    return _service().snapshot()


@web_app.app.delete("/api/tasks/finished")
async def api_tasks_clear_finished():
    return {"success": True, "removed": _service().clear_finished()}


@web_app.app.post("/api/tasks/{task_id}/cancel")
async def api_task_cancel(task_id: str):
    try:
        return {"success": True, **_service().cancel(task_id)}
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Задача не найдена") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@web_app.app.post("/api/tasks/{task_id}/rerun")
async def api_task_rerun(task_id: str):
    try:
        return {"success": True, **_service().rerun(task_id)}
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Исходник задачи недоступен") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


__all__ = ["api_task_cancel", "api_task_rerun", "api_tasks", "api_tasks_clear_finished"]
