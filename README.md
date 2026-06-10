# TextAlchemy

**Универсальный инструментарий обработки научно-учебных документов.**

Объединяет четыре подсистемы в единый CLI и веб-интерфейс:

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   EXTRACT   │    │   CONVERT    │    │   ORGANIZE   │    │   GENERATE   │
│  DOCX→TEX   │    │   PDF→DOCX   │    │ Библ.→Файлы  │    │  Шаблоны→Doc │
│  DOCX→LaTeX │    │              │    │  ГОСТ-ренейм │    │              │
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
uv sync              # установка зависимостей
textalchemy --help   # справка
textalchemy web      # веб-интерфейс на http://127.0.0.1:8000
```

## Команды CLI

| Команда | Описание | Пример |
|---------|----------|--------|
| `textalchemy extract` | Извлечение текста/LaTeX из DOCX | `textalchemy extract file.docx --format latex` |
| `textalchemy convert` | Пакетная конвертация PDF→DOCX | `textalchemy convert -i ./pdfs -o ./docs` |
| `textalchemy match` | Сопоставить и переименовать PDF | `textalchemy match -s ./literature -b bib.txt` |
| `textalchemy gost` | Форматирование в ГОСТ Р 7.0.100 | `textalchemy gost -i bib.txt -o gost.txt` |
| `textalchemy stats` | Статистика библиотеки | `textalchemy stats -s ./literature -b bib.txt` |
| `textalchemy export` | Экспорт библиографии | `textalchemy export -i bib.txt -f markdown` |
| `textalchemy bibtex` | Генерация .bib из PDF | `textalchemy bibtex -s ./pdfs -o out.bib` |
| `textalchemy init` | Создать конфиг | `textalchemy init -o config.json` |
| `textalchemy generate` | Генерация документов из шаблонов | `textalchemy generate report.docx output.docx -p title="Отчёт"` |
| `textalchemy recognize` | OCR распознавание | `textalchemy recognize scan.png --lang rus+eng` |
| `textalchemy web` | Запуск веб-интерфейса | `textalchemy web --port 8080` |

## Веб-интерфейс

Доступные страницы:

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
├── core/          # Общие утилиты, конфиг, исключения
├── extract/       # Извлечение содержимого DOCX → текст/LaTeX
├── convert/       # Конвертация PDF → DOCX (pdf2docx, PyMuPDF, LibreOffice)
├── organize/      # Парсинг библиографии, fuzzy matching, ренейм, ГОСТ
├── generate/      # Генерация документов из шаблонов
├── recognize/     # OCR (Tesseract/EasyOCR + stub), layout, классификация
├── cli/           # Обработчики CLI-команд
└── web/           # Веб-интерфейс (FastAPI + Jinja2)
```

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
uv run pytest tests/     # тесты (106 шт.)
uv run pytest --cov=textalchemy  # coverage
```

## Лицензия

MIT
