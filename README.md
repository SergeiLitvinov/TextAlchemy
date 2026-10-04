<img src="https://raw.githubusercontent.com/SergeiLitvinov/TextAlchemy/main/doc/assets/documentation-logo.svg" width="64" height="64" align="right" alt="TextAlchemy">

# TextAlchemy

**Документы в нужном формате. Результат под контролем.**

[![CI](https://github.com/SergeiLitvinov/TextAlchemy/actions/workflows/ci.yml/badge.svg)](https://github.com/SergeiLitvinov/TextAlchemy/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/SergeiLitvinov/TextAlchemy?include_prereleases)](https://github.com/SergeiLitvinov/TextAlchemy/releases)
[![MIT code](https://img.shields.io/badge/code-MIT-blue)](doc/LICENSE)

[Документация](https://SergeiLitvinov.github.io/TextAlchemy/) · [Руководство](doc/guide/index.md) · [Код](doc/reference/code.md) · [Выпуски](https://github.com/SergeiLitvinov/TextAlchemy/releases) · [Лицензии поставки](doc/development/licenses.md)

Локальное приложение для научных и учебных документов: конвертация с отчётом о потерях, извлечение и OCR, заполнение DOCX-шаблонов, библиография и повторяемые конвейеры. Один набор сценариев доступен через Web, CLI и Python API.

Версия приложения: **0.2.0rc1**. Суффикс `rc` означает предварительный выпуск. [Подготовка и состав релиза](doc/development/releases.md).

Проект экосистемы [okidoki](https://github.com/search?q=user%3ASergeiLitvinov+topic%3Aokidoki&type=repositories), со своими версиями, тестами и выпусками.

## Возможности

| Задача | Что предоставляет приложение |
|---|---|
| Конвертация | Каталог доступных маршрутов; простой и экспертный режимы; один файл или пакет; история и повтор заданий |
| Контроль результата | Прогноз, диагностика потерь, структурное сравнение, измеренные визуальные показатели и строгие бюджеты |
| Распознавание | OCR и извлечение текста; выбор страниц PDF, порядок и классификация блоков; текстовый черновик |
| Шаблоны | Поля, условия и повторения в DOCX; schema и проверка данных; предпросмотр; DOCX/HTML/PDF |
| Литература | Каталог файлов, сопоставление с библиографией, BibTeX, ГОСТ, JSON/Markdown |
| Автоматизация | YAML/TOML/JSON-конвейеры, журнал шагов, CLI и Python API |
| Справка | Встроенное руководство `/help/`, локальный поиск, справочники и навигатор по коду |

Доступность форматов зависит от установленных дополнений и внешних программ. PDF-подготовка не является полноценным PDF-редактором. XLSX/ODS не поддерживаются. Прогноз не измеряет конкретный файл; отсутствие LOSS не гарантирует идентичность. [Ограничения](doc/guide/formats.md), [свидетельства проверок](doc/guide/verification.md).

## Быстрый старт

Python 3.11+ и `uv`; команды из локальной копии проекта:

```powershell
uv sync --extra web --extra docx --extra pptx --extra html
uv run textalchemy web
```

Откройте [приложение](http://127.0.0.1:8000/), затем «Руководство». Для базового CLI достаточно `uv sync`. Дополнения `pdf`, `epub`, `ocr` устанавливайте по необходимости: у них отдельные лицензионные условия и внешние компоненты. [Установка](doc/guide/index.md#установка-и-запуск), [лицензии](doc/development/licenses.md).

```powershell
uv run textalchemy plan txt docx --json
uv run textalchemy convert-file input.txt result.docx --json
uv run textalchemy run doc/examples/text-to-docx.yaml --json
```

## Архитектура

| Независимый проект | Ответственность |
|---|---|
| [OpenDoc](https://github.com/SergeiLitvinov/opendoc) | Модель документа, ресурсы, JSON, валидация и структурное сравнение |
| [OpenDoc Formats](https://github.com/SergeiLitvinov/opendoc-formats) | Импорт/экспорт форматов, LaTeX и нативный доступ к документам |
| TextAlchemy | Сценарии, интерфейс, OCR, шаблоны, библиография, политики качества, задачи и публикация результата |

Приложение подключает неизменённые официальные wheel OpenDoc 0.1.0 и OpenDoc Formats 0.3.0. Исходники соседних проектов не нужны. У библиотек свои контракты и планы; приложение не дублирует их обработчики. [Границы и обновление](doc/development/document-library.md).

## Документация и разработка

| Нужно | Документ |
|---|---|
| Выполнить задачу | [Руководство](doc/guide/index.md), [содержание](doc/reference/user-guide.md) |
| Найти команду или операцию | [CLI](doc/reference/cli.md), [конвейер](doc/reference/operations.md) |
| Найти реализацию | [Навигатор по коду](doc/reference/code.md), [Web-маршруты](doc/reference/web-routes.md) |
| Проверить зависимости | [Все пакеты и версии](doc/reference/dependencies.md), [условия лицензий](doc/development/licenses.md) |
| Подготовить выпуск | [Версии и релизы](doc/development/releases.md) |
| Посмотреть будущую работу | [Единственный активный TODO](doc/development/roadmap.md) |
| Изменить проект | [AGENTS.md](doc/development/AGENTS.md), [стандарты](doc/development/CODING_STANDARDS.md), [система документации](doc/development/documentation.md) |

Разработка: `uv sync --frozen --extra dev --extra docs --extra web --extra pdf --extra docx --extra pptx --extra html --extra epub`, затем `uv run ruff check` и `uv run pytest tests/ --cov=textalchemy`. Порог покрытия — 80%; браузерные проверки требуют `uv run playwright install chromium`. OCR проверяется с подставными движками; реальные движки устанавливаются отдельно для распознавания.

Справочники и поставляемая справка обновляются командой `uv run python -m tools.docs generate`; проверяются `uv run python -m tools.docs check`. Для предпросмотра: `uv run python -m tools.docs serve` (extra `docs`).

Собственный код — [MIT](doc/LICENSE). Зависимости и встроенный поиск имеют собственные лицензии; MIT проекта не заменяет их условия. Релиз не включает бинарники движков. Для готовых комплектов OCR и профилей с lxml остаются неподтверждённые разрешения; подробности — в условиях поставки. [Уведомления](doc/NOTICE).
