"""Pipeline: операции конвейера.

Встроенные операции регистрируются в реестре явно через
:func:`register_builtin_operations` (а не только побочным эффектом импорта).
Реестр: :mod:`textalchemy.core.registry`.
"""
from __future__ import annotations

#: Модули со встроенными @operation. Порядок важен: модули должны
#: импортироваться до первого вызова ``all_operations()``.
BUILTIN_OPERATION_MODULES = (
    "textalchemy.pipeline.bibliography",
    "textalchemy.pipeline.emails_op",
    "textalchemy.pipeline.extract",
    "textalchemy.pipeline.ingest",
    "textalchemy.pipeline.match",
    "textalchemy.pipeline.match_files",
    "textalchemy.pipeline.name",
    "textalchemy.pipeline.render",
    "textalchemy.pipeline.render_html",
    "textalchemy.pipeline.template",
)


def register_builtin_operations() -> None:
    """Явно зарегистрировать все встроенные операции в реестре.

    Идемпотентна и безопасна для повторного вызова, в том числе после
    ``reset()``: модули импортируются (декораторы срабатывают при первом
    импорте), а затем операции, помеченные ``@operation``, восстанавливаются
    из маркеров функций, если реестр был очищен. Это единственная точка
    входа, которую следует вызывать перед ``all_operations()``/``run_pipeline``
    — например, в CLI, Web-роутах или после ``reset()`` в тестах.
    """
    import importlib

    from textalchemy.core.registry import re_register, spec_for

    for module_name in BUILTIN_OPERATION_MODULES:
        importlib.import_module(module_name)
    for module_name in BUILTIN_OPERATION_MODULES:
        module = importlib.import_module(module_name)
        for attr_name in dir(module):
            spec = spec_for(getattr(module, attr_name, None))
            if spec is not None:
                re_register(spec)


register_builtin_operations()

__all__ = [
    "BUILTIN_OPERATION_MODULES",
    "register_builtin_operations",
]
