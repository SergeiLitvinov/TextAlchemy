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
| `extract.text` | `Document` | `Text` | Универсальный ридер (PDF/DOCX/TXT/DjVu) |
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
| `render.bibtex` | BibItem[] | str | BibItem[] → BibTeX |
| `render.gost` | BibItem[] | str | BibItem[] → ГОСТ Р 7.0.100 |
| `render.markdown` | BibItem[] | str | BibItem[] → Markdown |
| `render.json` | BibItem[] | str | BibItem[] → JSON |
| `render.emails.docx` | `list[str]` | Path | Email → Word-документ |
| `render.emails.txt` | `list[str]` | Path | Email → текстовый файл |
| `render.emails.debug` | `str` | Path | Отладочный текст распознавания → TXT |

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

### Извлечение email

`extract.emails` использует двухуровневый подход:
1. **Текстовый слой PDF** — если на странице >50 символов текста, email ищутся regex без OCR.
2. **OCR (Tesseract)** — для страниц без текстового слоя: OpenCV-предобработка (grayscale → medianBlur → adaptiveThreshold → morphology) + Tesseract через subprocess с таймаутом.

Результат можно сохранить в DOCX (`render.emails.docx`), TXT (`render.emails.txt`) или отладочный файл (`render.emails.debug`).

```bash
textalchemy emails scan.pdf -o result.docx --output-txt result.txt --debug
```

## Команды CLI

| Команда | Описание | Пример |
|---------|----------|--------|
| `textalchemy extract` | Извлечение текста/LaTeX из DOCX | `textalchemy extract file.docx --format latex` |
| `textalchemy convert` | Пакетная конвертация PDF→DOCX (по умолчанию fan-out) | `textalchemy convert -i ./pdfs -o ./docs` |
| `textalchemy convert-file` | Универсальная конвертация одного файла через лучший доступный маршрут | `textalchemy convert-file report.docx report.pdf --mode faithful` |
| `textalchemy plan` | Подбор маршрута и оценка сохранности функций документа | `textalchemy plan docx pdf --mode faithful --json` |
| `textalchemy pptx2html` | PPTX → автономный HTML | `textalchemy pptx2html -i deck.pptx -o ./out` |
| `textalchemy match` | Сопоставить и переименовать PDF | `textalchemy match -s ./literature -b bib.txt` |
| `textalchemy gost` | Форматирование в ГОСТ Р 7.0.100 | `textalchemy gost -i bib.txt -o gost.txt` |
| `textalchemy stats` | Статистика библиотеки | `textalchemy stats -s ./literature -b bib.txt` |
| `textalchemy export` | Экспорт библиографии | `textalchemy export -i bib.txt -f markdown` |
| `textalchemy bibtex` | Генерация .bib из PDF | `textalchemy bibtex -s ./pdfs -o out.bib` |
| `textalchemy init` | Создать конфиг | `textalchemy init -o config.json` |
| `textalchemy generate` | Генерация документов из шаблонов | `textalchemy generate report.docx output.docx -p title="Отчёт"` |
| `textalchemy recognize` | OCR распознавание | `textalchemy recognize scan.png --lang rus+eng` |
| `textalchemy run` | Запуск pipeline из YAML/TOML | `textalchemy run pipeline.yaml` |
| `textalchemy run --list` | Список зарегистрированных операций | — |
| `textalchemy emails` | Извлечение email из PDF/DOCX/TXT + сохранение | `textalchemy emails in.pdf -o result.docx --debug` |
| `textalchemy web` | Запуск веб-интерфейса | `textalchemy web --port 8080` |

## Веб-интерфейс

| URL | Описание |
|-----|----------|
| `/` | Дашборд со статистикой |
| `/bibliography` | CRUD библиографии + импорт |
| `/matching` | Сопоставление файлов с библиографией |
| `/rename` | Предпросмотр переименования |
| `/reports` | Статистика и результаты |
| `/export` | Экспорт JSON / Markdown / ГОСТ |
| `/extract` | Извлечение текста из DOCX |
| `/convert` | Конвертация PDF→DOCX |
| `/recognize` | OCR распознавание |
| `/generate` | Генерация из шаблонов |

## Архитектура

```
src/textalchemy/
├── core/              # базовые типы (Document, Text, Match, Signal)
│                      # + реестр операций @operation("id")
├── formats/           # парсеры форматов: pdf, docx, txt (djvu)
├── pipeline/          # стадии конвейера
│   ├── ingest.py      # @operation("ingest.file")
│   ├── extract.py     # @operation("extract.text")
│   ├── emails_op.py   # @operation("extract.emails", "render.emails.*")
│   ├── match.py       # @operation("match.bibliography")
│   ├── match_files.py # @operation("match.files") — батч-матчинг
│   ├── bibliography.py# @operation("bibliography.parse/smart_parse")
│   ├── name.py        # @operation("name.from_match")
│   ├── render.py      # @operation("render.*")
│   ├── signals.py     # автор/title/год/doi сигналы для матчинга
│   └── runner.py      # YAML/TOML/JSON → последовательность операций
├── convert/           # PDF→DOCX (3 бэкенда + FanOut) + PPTX→HTML
├── extract/           # legacy: docx→text/latex
├── organize/          # legacy: bibparser, match, gost
├── recognize/         # OCR / layout / classifier / emails
├── generate/          # шаблоны документов
├── web/               # FastAPI + Jinja2
├── cli/               # обработчики CLI
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
uv run pytest tests/     # все тесты (427 шт.)
uv run pytest --cov=textalchemy  # coverage
uv run textalchemy run --list    # зарегистрированные операции
```

## Лицензия

MIT
