# Интерфейс шаблонизатора

`textalchemy.templating` — модуль внутри TextAlchemy с отдельной границей зависимостей. Он принимает модель OpenDoc и данные, возвращает новую заполненную модель. Для работы нужны OpenDoc, Jinja2 и стандартная библиотека Python. Отдельный пакет пока не создан: выделение оправдано при появлении второго приложения с конкретными требованиями.

## Работа с моделью

```python
from opendoc_model.document_model import DocumentModel, Paragraph, Section, TextRun
from textalchemy.templating import (
    TemplateField, TemplateSchema, TemplateValueType,
    inspect_document_template, render_document_template,
)

template = DocumentModel(sections=[Section(blocks=[
    Paragraph(content=[TextRun("Служебная записка: {{ person }}")]),
])])
schema = TemplateSchema(fields=[TemplateField("person", TemplateValueType.STRING)])
inspection = inspect_document_template(template, schema)
if not inspection.valid:
    raise ValueError(inspection.errors)
result = render_document_template(template, {"person": "Иванов Иван Иванович"}, schema=schema)
assert result.sections[0].blocks[0].plain_text == "Служебная записка: Иванов Иван Иванович"
assert template.sections[0].blocks[0].plain_text == "Служебная записка: {{ person }}"
```

В публичный интерфейс входят `render_document_template`, `inspect_document_template`, `validate_template_data`, классы схемы, `TemplateImage`, `TemplateFormula`, `TemplateInspection` и `TemplateError`. Условия, циклы, строки таблиц, колонтитулы, оглавление и перекрёстные ссылки используют прежний синтаксис. Схема задаёт типы, обязательность и значения по умолчанию. Рендер не изменяет шаблон, схему или данные пользователя; `strict=False` допускает отсутствующие переменные, но переданная схема продолжает проверять обязательные поля и типы.

## Подключаемые ресурсы

Изображение можно передать как `TemplateImage(data=..., media_type="image/png")`. Ядро само не читает файлы. Если задан `TemplateImage(source=...)`, вызывающий код передаёт `image_loader`: функцию, принимающую `TemplateImage` и возвращающую `bytes`. Она определяет, откуда и по каким правилам получить ресурс. Ошибка загрузчика при рендере преобразуется в `TemplateError` с сохранением причины. Готовые узлы `Image` и `Formula` OpenDoc также поддерживаются.

`reference_formatter` принимает одну запись библиографии и возвращает текст или `None`, чтобы пропустить запись. Ядро добавляет нумерацию и абзацы. По умолчанию принимаются строки и словари с авторами, названием и годом; это простое текстовое представление, без обещания оформления по ГОСТ. Специальное оформление подключает приложение.

## Адаптеры TextAlchemy

`textalchemy.generate` сохраняет прежний публичный интерфейс. Его адаптеры читают изображения с диска, преобразуют библиографические записи и применяют существующий форматтер, загружают JSON/YAML/TOML и выполняют чтение DOCX → рендер → экспорт. Ошибки ядра переводятся в прежний `GenerateError`, поэтому CLI, конвейер, Web-форма и черновой предпросмотр сохраняют свой контракт. Классы схемы и типизированных значений общие для обоих интерфейсов.

Граница закреплена тестами: новый процесс блокирует импорты остальных модулей приложения и тяжёлых обработчиков, проверка исходников допускает только внутренние импорты, OpenDoc, Jinja2 и стандартную библиотеку. Отдельные сценарии проверяют неизменность входов, подключаемые ресурсы, библиографию и совместимость ошибок. Пути к реализации и тестам автоматически представлены в [навигаторе](../reference/code.md).

Сейчас шаблонизатор не выделяется в соседний проект. Он не распознаёт автоматически поля в произвольном документе и не заменяет редактор шаблонов. Библиотека OpenDoc остаётся внешней зависимостью и в рамках этой работы не меняется.
