"""Причины недоступности режима с разделением поддержки, реализации и зависимостей."""

from __future__ import annotations

from textalchemy.convert.executor import ConversionExecutor
from textalchemy.core.conversion_graph import ConversionPlan
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.types import DocFormat


def unavailable_reason(
    executor: ConversionExecutor,
    source: DocFormat,
    target: DocFormat,
    mode: ConversionMode,
    runtime_plan: ConversionPlan | None,
) -> dict[str, object]:
    if runtime_plan is not None:
        return {
            "code": "web_route_unsupported",
            "message": "Маршрут требует промежуточных файлов и пока не доступен через веб-интерфейс.",
        }
    implemented = executor.registry.plan(source, target, mode=mode, available=lambda step: step.id in executor.backends)
    if implemented is not None:
        missing = [item for item in implemented.executable_requirements if not executor.requirement_checker(item)]
        if missing:
            return {
                "code": "missing_dependencies",
                "requirements": missing,
                "message": "Для маршрута не найдены компоненты: " + ", ".join(missing) + ".",
            }
    theoretical = executor.registry.plan(source, target, mode=mode)
    if theoretical is not None:
        return {"code": "backend_unavailable", "message": "Маршрут описан, но его обработчик не подключён в этой установке."}
    return {"code": "unsupported_mode", "message": "Преобразование в этом режиме пока не поддерживается движком."}
