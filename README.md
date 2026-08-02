# TextAlchemy

**Универсальный инструментарий обработки научно-учебных документов.**

Объединяет подсистемы в единый конвейер (pipeline) и CLI:

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   EXTRACT   │    │   CONVERT    │    │   ORGANIZE   │    │   GENERATE   │
│  DOCX→TEX   │    │   PDF→DOCX   │    │ Библ.→Файлы  │    │  Шаблоны→Doc │
│  DOCX→LaTeX │    │  PPTX→HTML   │    │  ГОСТ-ренейм │    │              │
└─────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                         ┌──────────────┐
                         │  RECOGNIZE   │
                         │  OCR / Layout│
                         └──────────────┘
```

## Быстрый старт

```bash
git clone <repo>
cd TextAlchemy
uv sync --all-extras       # установка зависимостей
textalchemy --help         # справка
textalchemy web            # веб-интерфейс на http://127.0.0.1:8000
textalchemy run --list     # список операций pipeline
```

## Pipeline (новое)

Конвейер — это последовательность атомарных операций, описанная в YAML/TOML/JSON.
Каждая операция — функция с декоратором `@operation("id")` в одном из модулей
`pipeline/`. Контекст (`ctx`) передаёт значения между шагами.

```yaml
# demo.yaml
steps:
  - op: ingest.file                  # открыть файл
    output: doc
    params: {path: input.txt}

  - op: extract.text                 # Document → Text
    input: doc
    output: text

  - op: render.latex                 # Text → LaTeX
    input: text
    output: tex
    params: {title: "Demo"}

output: tex
```

```bash
$ textalchemy run demo.yaml
  [OK] ingest.file -> doc
  [OK] extract.text -> text
  [OK] render.latex -> tex
Final: \documentclass[12pt,a4paper]{article}...
```

Полный список операций:

| Op | Вход | Выход | Описание |
|---|---|---|---|---|
| `ingest.file` | path | `Document` | Открыть файл, посчитать SHA-256 |
| `extract.text` | `Document` | `Text` | Универсальный ридер (PDF/DOCX/TXT/DjVu/EPUB) |
| `extract.pdf_model` | `Document` (PDF) | `DocumentModel` | PDF → богатая модель (геометрия, таблицы, изображения, вектор) + опционально OCR |
| `extract.pptx_model` | `Document` (.pptx) | `DocumentModel` | PPTX → богатая модель (слайды, фигуры, таблицы, изображения, диаграммы, формулы OMML) |
| `extract.emails` | `Document` | `list[str]` | Извлечение email: текстовый слой PDF + OCR |
| `match.bibliography` | `Text`, `Document`, BibItem[] | `Match` | Сопоставить документ со списком записей |
| `match.files` | path, BibItem[] | Match[] | Батч-матчинг директории; копирует в `output_dir` |
| `bibliography.parse` | path | BibItem[] | Распарсить файл библиографии |
| `bibliography.smart_parse` | text | BibItem[] | Auto-detect формата библиографии |
| `name.from_match` | `Match` | str | Сгенерировать имя файла по BibItem |
| `render.html.pptx` | `Document` (.pptx) | `ConversionResult` | PPTX → автономный HTML-просмотрщик |
| `render.latex` | `Text` | str | Text → LaTeX (статья, с преамблой) |
| `render.latex.pandoc` | `Text` | str | Text → LaTeX через pandoc |
| `render.docx` | `Text` | Path | Text → DOCX |
| `render.docx_model` | `DocumentModel` | Path | DocumentModel → DOCX через `write_docx_model` |
| `render.bibtex` | BibItem[] | str | BibItem[] → BibTeX |
| `render.gost` | BibItem[] | str | BibItem[] → ГОСТ Р 7.0.100 |
| `render.markdown` | BibItem[] | str | BibItem[] → Markdown |
| `render.json` | BibItem[] | str | BibItem[] → JSON |
| `render.emails.docx` | `list[str]` | Path | Email → Word-документ |
| `render.emails.txt` | `list[str]` | Path | Email → текстовый файл |
| `render.emails.debug` | `str` | Path | Отладочный текст распознавания → TXT |
| `template.render` | `DocumentModel` | `DocumentModel` | Заполнить модель данными: переменные, условия, циклы |

Полный список — `textalchemy run --list`.

### Контракт операций

- Все параметры **keyword-only** (`*, text: Text, title: str = ""`).
- Имя входного параметра задаётся в `@operation(..., input_param="text")` —
  runner подставляет туда значение из поля `input:` шага.
- `params: {x: $y}` — ссылка на `ctx["y"]` (через `$`-префикс).
- `params: {x: "{title}"}` — `str.format(**ctx)`.
- Поля верхнего уровня YAML (вне `steps:`) — начальный контекст.

### PDF-извлечение

`extract.text` для PDF использует цепочку движков: `pdfplumber → pypdf → pymupdf`.
Первый успешно вернувший непустой результат используется; предупреждения от
предыдущих движков сохраняются в `Text.warnings`.

Для богатой структуры (reading order, таблицы, классификация подписей/колонтитулов,
растровые и векторные изображения) и объединения текстового слоя с OCR используется
геометрический анализ PyMuPDF (`formats/pdf_geometry.py`, `pdf_layout.py`, `pdf_classify.py`)
с последующим слиянием OCR (`formats/pdf_ocr_merge.py`). В конвейере это доступно как
`extract.pdf_model` (→ `DocumentModel`) с параметрами `use_ocr`, `ocr_backend`, `handwriting`, `use_gpu`.

### PPTX-импорт на общей модели

`extract.pptx_model` (→ `DocumentModel`) переводит презентацию в богатую модель:
слайды → секции, фигуры → блоки с абсолютной геометрией (EMU → pt), текст → абзацы
с форматированием и гиперссылками, OMML-формулы, изображения (в ресурсы модели),
таблицы, диаграммы (данные в `properties["pptx"]["chart"]`), фон и заметки.
Группы фигур разворачиваются с учётом трансформации `off/ext/chOff/chExt`.
Автофигуры/коннекторы сохраняются в `properties["pptx"]["shape"]` (`prst`, заливка,
обводка) и рендерятся общим HTML-рендерером как SVG-фон. Стили и геометрия
placeholder-ов наследуются по цепочке слайд → layout → master (`p:txStyles`).

Благодаря общему `DocumentModel` маршруты `PPTX → HTML/DOCX/PDF` проходят через
capability-планировщик: `pptx.model → model.html` (общий HTML-рендерер),
`pptx.model → model.docx` и т.д. Легаси-конвертер `pptx.html` остаётся как
fallback-маршрут повышенной стоимости.

### Извлечение email

`extract.emails` использует двухуровневый подход:
1. **Текстовый слой PDF** — если на странице >50 символов текста, email ищутся regex без OCR.
2. **OCR (Tesseract)** — для страниц без текстового слоя: OpenCV-предобработка (grayscale → medianBlur → adaptiveThreshold → morphology) + Tesseract через subprocess с таймаутом.

Результат сохраняется в DOCX (`render.emails.docx`), TXT (`render.emails.txt`) или отладочный файл (`render.emails.debug`) через конвейер:

```yaml
steps:
  - op: ingest.file
    output: doc
    params: {path: scan.pdf}
  - op: extract.emails
    input: doc
    output: emails
  - op: render.emails.docx
    input: emails
    output: result
    params: {output_path: result.docx}
output: result
```

## Команды CLI

| Команда | Описание | Пример |
|---------|----------|--------|
| `textalchemy extract` | Извлечение текста/LaTeX из DOCX | `textalchemy extract file.docx --format latex` |
| `textalchemy convert` | Пакетная конвертация PDF→DOCX (по умолчанию fan-out) | `textalchemy convert -i ./pdfs -o ./docs` |
| `textalchemy convert-file` | Универсальная конвертация одного файла через лучший доступный маршрут | `textalchemy convert-file report.docx report.pdf --mode faithful` |
| `textalchemy plan` | Подбор маршрута и оценка сохранности функций документа | `textalchemy plan docx pdf --mode faithful --json` |
| `textalchemy inspect` | Отчёт о структуре и качестве DOCX/PDF/JSON-модели | `textalchemy inspect file.docx --json` |
| `textalchemy pptx2html` | PPTX → автономный HTML | `textalchemy pptx2html -i deck.pptx -o ./out` |
| `textalchemy match` | Сопоставить и переименовать PDF | `textalchemy match -s ./literature -b bib.txt` |
| `textalchemy gost` | Форматирование в ГОСТ Р 7.0.100 | `textalchemy gost -i bib.txt -o gost.txt` |
| `textalchemy stats` | Статистика библиотеки | `textalchemy stats -s ./literature -b bib.txt` |
| `textalchemy export` | Экспорт библиографии | `textalchemy export -i bib.txt -f markdown` |
| `textalchemy bibtex` | Генерация .bib из PDF | `textalchemy bibtex -s ./pdfs -o out.bib` |
| `textalchemy init` | Создать конфиг | `textalchemy init -o config.json` |
| `textalchemy generate` | Генерация документов из шаблонов | `textalchemy generate report.docx output.docx -p title="Отчёт"` |
| `textalchemy template-check` | Проверка DOCX-шаблона, схемы и данных без генерации | `textalchemy template-check report.docx --schema schema.json` |
| `textalchemy recognize` | OCR распознавание | `textalchemy recognize scan.png --lang rus+eng` |
| `textalchemy run` | Запуск pipeline из YAML/TOML/JSON | `textalchemy run pipeline.yaml` |
| `textalchemy run --list` | Список зарегистрированных операций | — |
| `textalchemy completion` | Скрипт автодополнения для bash/zsh/fish | `textalchemy completion bash` |
| `textalchemy web` | Запуск веб-интерфейса | `textalchemy web --port 8080` |

## Веб-интерфейс

| URL | Описание |
|-----|----------|
| `/` | Дашборд со статистикой |
| `/bibliography` | CRUD библиографии + импорт |
| `/matching` | Сопоставление файлов с библиографией + предпросмотр переименования |
| `/reports` | Статистика и результаты |
| `/export` | Экспорт JSON / Markdown / ГОСТ |
| `/extract` | Извлечение текста из DOCX |
| `/convert` | Конвертация (маршрут по режиму качества) + отчёт |
| `/pipeline` | Запуск конвейера по YAML/TOML |
| `/recognize` | OCR распознавание |
| `/generate` | Генерация из шаблонов |

## Архитектура

```
src/textalchemy/
├── core/              # базовые типы (Document, Text, Match, Signal, BibItem)
│                      # + DocumentModel (document_model.py), реестр @operation("id"),
│                      #   граф конвертеров (conversion_graph.py), codec (document_codec.py)
├── formats/           # атомарные ридеры: pdf, docx, txt, djvu, epub
│                      #   + PDF-геометрия/семантика/классификация, images, OCR-merge
├── ooxml/             # общий OPC package graph и relationships для DOCX/PPTX
├── pipeline/          # стадии конвейера
│   ├── ingest.py      # @operation("ingest.file")
│   ├── extract.py     # @operation("extract.text", "extract.pdf_model", "extract.pptx_model")
│   ├── emails_op.py   # @operation("extract.emails", "render.emails.*")
│   ├── match.py       # @operation("match.bibliography")
│   ├── match_files.py # @operation("match.files") — батч-матчинг
│   ├── bibliography.py# @operation("bibliography.parse/smart_parse")
│   ├── name.py        # @operation("name.from_match")
│   ├── render.py      # @operation("render.*", "render.docx_model")
│   ├── render_html.py # @operation("render.html.pptx")
│   ├── template.py    # @operation("template.render")
│   ├── signals.py     # автор/title/год/doi сигналы для матчинга
│   └── runner.py      # YAML/TOML/JSON → последовательность операций
├── convert/           # PDF→DOCX (3 бэкенда + FanOut), DOCX→LaTeX, PPTX→HTML,
│                      #   DocumentModel importer/exporter'ы, capability registry + executor├── quality/           # визуальные метрики и perceptual regression
├── extract/           # legacy: docx→text/latex, emails, fix_encoding
├── organize/          # legacy: bibparser, match, gost
├── recognize/         # OCR (3 бэкенда) / layout / classifier / emails
├── generate/          # шаблоны документов (DSL + схема + model_template)
├── web/               # FastAPI + Jinja2 (routes/, templates/, static/)
├── cli/               # обработчики CLI (15 модулей)
└── __main__.py        # argparse + dispatch
```

**Принцип:** горизонтальные подсистемы остались, но конвейерная логика
вынесена в `pipeline/` и `core/registry.py`. Каждая операция —
изолированная, тестируемая единица с явным контрактом входа/выхода.

## Установка

```bash
pip install -e .                     # базовая установка
pip install -e ".[ocr,web,dev]"      # полная (OCR + веб + разработка)
```

Для OCR дополнительно требуется Tesseract (системный пакет) или easyocr.

## Разработка

```bash
uv sync --all-extras
uv run ruff check        # линтинг
uv run pytest tests/     # все тесты (660 шт.)
uv run pytest --cov=textalchemy  # coverage
uv run textalchemy run --list    # зарегистрированные операции
```

## Лицензия

MIT
