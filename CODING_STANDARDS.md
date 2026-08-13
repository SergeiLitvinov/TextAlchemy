# Стандарты программирования TextAlchemy

## 1. Язык и среда

- **Язык**: Python 3.11+
- **Сборка**: `uv` (uv sync, uv run, uv add)
- **Кодировка**: UTF-8. На Windows `__main__.py` принудительно переключает stdout/stderr на UTF-8.
- **Пакет**: `src/` layout (`[tool.setuptools.packages.find] where = ["src"]`)

## 2. Линтинг и форматирование

Инструмент — **Ruff**. Конфигурация в `pyproject.toml`:

| Параметр | Значение |
|----------|----------|
| line-length | 130 |
| target-version | py311 |
| select | E, F, I, N, W, BLE |

Перед коммитом обязательно:

```bash
uv run ruff check --fix
uv run ruff format
```

Игнорирования (per-file) указаны в `pyproject.toml` — не расширять без веской причины.

## 3. Комментарии и докстринги

- **Докстринги модулей**: русский язык, описывают назначение модуля и ключевые решения. Первая строка — краткое описание.
- **Докстринги функций/методов**: русский язык, описывают возвращаемое значение и важные детали. Опциональны для очевидных однострочных функций.
- **Комментарии в коде**: не ставить. Если код непонятен без комментария — упростить код, а не добавлять комментарий.
- **Исключение**: `# noqa: F401` и аналогичные подавители линтера с указанием правила.

## 4. Именование

| Сущность | Стиль | Пример |
|----------|-------|--------|
| Переменные | `snake_case` | `plain`, `best_score`, `input_path` |
| Функции/методы | `snake_case` | `read_pdf()`, `collect_signals()` |
| Классы | `PascalCase` | `BibItem`, `ConversionReport`, `OcrEngine` |
| Константы модуля | `UPPER_SNAKE_CASE` | `_PREAMBLE`, `FORMAT_VERSION` |
| Перечисления (Enum) | `PascalCase`; значения `snake_case` | `class DocFormat(Enum): PDF = "pdf"` |
| Приватные (внутри модуля) | `_leading_underscore` | `_normalize_items()`, `_REGISTRY` |
| Защищённые (класс) | `_leading_underscore` | `_prepare()` |
| Пакеты/директории | `snake_case` | `textalchemy`, `core`, `convert_file_cmd` |
| Тип-алиасы | `PascalCase` | `TypeAlias`, `Any` |

## 5. Аннотации типов

- Обязательны для всех функций (включая `__init__` и методы классов).
- Импорт `from __future__ import annotations` — первая строка после докстринга в каждом модуле.
- `Optional[X]` предпочтительнее `X | None` (единообразие с существующей базой).
- Для коллекций: `list[X]`, `dict[str, X]`, `set[X]`, `tuple[X, ...]`.
- Для Union: `Union[str, Path]`.
- `Any` только там, где тип действительно динамический.
- Возвращаемый тип всегда явный (даже `-> None`).

## 6. Структура файла

```
"""Докстринг модуля на русском языке."""

from __future__ import annotations

# 1) Стандартная библиотека
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# 2) Третьи стороны
import yaml

# 3) Внутренние
from textalchemy.core.registry import operation
from textalchemy.core.types import Document, Text
```

Разделы разделяются одной пустой строкой.

## 7. Стиль кода

- **Длины строк**: до 130 символов.
- **Dataclasses** предпочтительнее ручного `__init__`.
- **frozen=True** для иммутабельных структур (`@dataclass(frozen=True)`).
- **Enum** через `class X(str, Enum)` — значения строковые.
- **Keyword-only аргументы** (`*, name: str`) для всех pipeline-операций и публичных функций.
- **None-проверка**: `if x is None`, `if x is not None`.
- **Булева проверка**: `if not items:`, `if text:` (не `len(x) > 0`).
- **Методы экземпляра**: первый аргумент `self`, классовые — `cls`, статические — `@staticmethod`.
- **Свойства**: `@property` для вычисляемых полей (см. `Match.score`, `Signal.contribution`).
- **Временные файлы**: `tempfile.NamedTemporaryFile` + `finally: unlink()`.
- **Импорты внутри функций**: разрешены для тяжёлых/опциональных зависимостей (lazy import).

## 8. Контракт pipeline-операций

```python
@operation(
    "namespace.op",
    input_type="InputType",
    output_type="OutputType",
    input_param="input_name",
    description="Краткое описание на русском.",
    tags=["tag1", "tag2"],
)
def my_operation(*, input_name: InputType, param1: str = "default") -> OutputType:
    ...
```

Правила:
- Все параметры keyword-only.
- `input_param` совпадает с именем аргумента функции.
- Возвращаемое значение — JSON-сериализуемое, либо `Path`/`Document`/`Text`/`Match`/`BibItem`.
- Функция не должна иметь побочных эффектов вне возвращаемого значения.
- Ошибки — исключения (не возврат кода ошибки).

## 9. Тесты

- **Фреймворк**: pytest.
- **Расположение**: `tests/` — зеркалирует `src/textalchemy/` (подпапки `pipeline/`, `convert/`, `core/` и т.д.).
- **Именование файлов**: `test_<module>.py`.
- **Именование функций**: `test_<описание_случая>`.
- **Использование `isolated()`** для изоляции реестра, никогда `reset()`.
- **Импорт модуля операции** в тесте, если тест проверяет реестр: `from textalchemy.pipeline import render as _render_op  # noqa: F401`.
- **Команда**: `uv run pytest tests/ -v --tb=short`.
- **Параметризация**: `@pytest.mark.parametrize` для табличных тестов.

## 10. Обработка ошибок

- Не подавлять исключения без явной причины (`# noqa: BLE001` — только с обоснованием в том же файле или per-file в pyproject.toml).
- Ошибки валидации: `ValueError` с информативным сообщением на русском.
- Отсутствующие опциональные зависимости: возвращать результат с `warnings=[...]`, а не бросать `ImportError`.
- `try/except` покрывать минимально необходимый блок (не весь файл).
- `except Exception: logger.exception(...)` — только в `__main__.py` верхнего уровня.

## 11. Импорты и зависимости

- **Core-зависимости**: в `[project.dependencies]` (PyYAML, python-docx, pymupdf и т.д.).
- **Опциональные**: `[project.optional-dependencies] ocr = [...]`.
- Тяжёлые опциональные зависимости — lazy import внутри функции.
- Не добавлять зависимость, которая импортируется только в одном тесте.
- Версии фиксировать через `>=` (не `==`, не `~=`).

## 12. Работа с файловой системой

- `Path` из `pathlib` — всегда, не `os.path`.
- `Path(__file__).parent` для доступа к ассетам внутри пакета.
- `out.parent.mkdir(parents=True, exist_ok=True)` перед записью.
- Временные каталоги: `tempfile.mkdtemp()` + очистка в `finally:`.
- Удаление файлов: `Path.unlink(missing_ok=True)`.

## 13. Работа с Git

- Язык commit-сообщений: английский.
- Формат: `<глагол в imperative>: <краткое описание>`, например `feat: add PDF reading order detection`.
- Типы коммитов: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.
- Никаких секретов и .env в репозитории.

## 14. MANIFEST.in

При добавлении не-Python ассетов (css, js, шаблоны, lua-фильтры) — обязательно расширять `MANIFEST.in`:
```
recursive-include src/textalchemy/путь/к/ассетам *
```

## 15. Архитектурные границы

- Модуль имеет одну причину для изменения. Маршрут Web не выполняет конвертацию, конвертер не знает об HTTP, а шаблон не содержит бизнес-правил.
- Направление зависимостей: `presentation/web → application/use-cases → domain/core`. Работа с файлами, OOXML, OCR и внешними движками подключается через infrastructure adapters.
- Этапы преобразования разделяются явными типизированными контрактами: `parse → normalize → analyze/layout → render/serialize → verify`.
- Format-specific данные хранятся в namespaced extensions и обрабатываются адаптером формата; общая модель не импортирует реализации DOCX/PDF/PPTX.
- Новые Python-модули ориентируются на 400 строк. Файл больше 600 строк требует декомпозиции либо документированного исключения для таблиц данных/сгенерированного кода.
- Jinja-шаблоны отвечают за разметку. Повторяемые части оформляются partial/component, а page state, API-вызовы и DOM-rendering размещаются в отдельных JS-модулях.
- Route handler выполняет только разбор/валидацию запроса, вызов use-case и формирование ответа. Очереди, workspace, planning и persistence не реализуются внутри handler.
- Запрещены циклические импорты и обратные зависимости из `core` в `web`, CLI или конкретный backend.
