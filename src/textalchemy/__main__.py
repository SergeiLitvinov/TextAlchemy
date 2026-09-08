import argparse
import sys
from typing import Optional

from textalchemy import __version__ as VERSION
from textalchemy.cli import (
    cmd_bibtex,
    cmd_completion,
    cmd_convert,
    cmd_convert_file,
    cmd_export,
    cmd_extract,
    cmd_generate,
    cmd_gost,
    cmd_init,
    cmd_inspect,
    cmd_match,
    cmd_plan,
    cmd_pptx2html,
    cmd_recognize,
    cmd_run,
    cmd_stats,
    cmd_template_check,
    cmd_web,
)
from textalchemy.core.logging import configure_logging, get_logger

logger = get_logger("cli")

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _setup_parser():
    parser = argparse.ArgumentParser(
        prog="textalchemy",
        description="TextAlchemy — универсальный инструментарий обработки документов",
    )
    parser.add_argument("--version", action="version",
                        version=f"TextAlchemy {VERSION}")
    parser.add_argument("-v", "--debug", action="store_true",
                        help="Подробное логирование (DEBUG)")
    parser.add_argument("-c", "--config", help="Путь к конфигурационному файлу JSON")

    sub = parser.add_subparsers(dest="command", help="Команды")

    p = sub.add_parser("extract", help="Извлечение текста/LaTeX из DOCX")
    p.add_argument("input", type=str, help="Входной DOCX файл")
    p.add_argument("output", type=str, nargs="?", help="Выходной файл")
    p.add_argument("--format", choices=["text", "latex", "pandoc"], default="text")
    p.add_argument("--doc-type", choices=["manuscript", "abstract"], default="manuscript")
    p.add_argument("--json", action="store_true", help="Вывод в JSON")

    p = sub.add_parser("convert", help="Конвертация PDF в DOCX")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output")
    p.add_argument("--tool", choices=["pdf2docx", "pymupdf", "libreoffice", "fanout"], default="fanout")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true", help="Вывод в JSON")

    p = sub.add_parser("pptx2html", help="Конвертация .pptx в автономный HTML-просмотрщик")
    p.add_argument("-i", "--input", required=True, help="Путь к .pptx файлу")
    p.add_argument("-o", "--output", required=True, help="Директория для HTML-результата")
    p.add_argument("--no-assets", action="store_true", help="Не копировать встроенные css/js (если они уже есть)")
    p.add_argument("--json", action="store_true", help="Вывод в JSON")

    p = sub.add_parser("match", help="Сопоставить и переименовать файлы")
    p.add_argument("-s", "--source", default="./literature_files")
    p.add_argument("-o", "--output", default="./renamed")
    p.add_argument("-b", "--bibliography")
    p.add_argument("-t", "--threshold", type=float, default=0.30)
    p.add_argument("--json", action="store_true", help="Сохранить отчёт в JSON")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("gost", help="Конвертация библиографии в ГОСТ")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--json", action="store_true", help="Вывод в JSON")

    p = sub.add_parser("stats", help="Статистика библиотеки")
    p.add_argument("-s", "--source", default="./literature_files")
    p.add_argument("-o", "--output", default="./renamed")
    p.add_argument("-b", "--bibliography")
    p.add_argument("--json", action="store_true", help="Вывод в JSON")

    p = sub.add_parser("export", help="Экспорт библиографии")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output")
    p.add_argument("-f", "--format", choices=["json", "markdown", "gost"], default="json")

    p = sub.add_parser("generate", help="Генерация из шаблонов")
    p.add_argument("template", type=str, nargs="?", default=None)
    p.add_argument("output", type=str, nargs="?", default=None)
    p.add_argument("-p", "--param", action="append")
    p.add_argument("--list", action="store_true")
    p.add_argument("--templates-dir", type=str)
    p.add_argument("--data", help="Данные шаблона JSON/YAML/TOML")
    p.add_argument("--schema", help="Схема данных JSON/YAML/TOML")
    p.add_argument("--no-strict", action="store_true", help="Разрешить отсутствующие переменные")
    p.add_argument("--json", action="store_true", help="Вывод в JSON")

    p = sub.add_parser("template-check", help="Проверить DOCX-шаблон и схему без генерации")
    p.add_argument("template", help="Путь к DOCX-шаблону")
    p.add_argument("--schema", help="Схема данных JSON/YAML/TOML")
    p.add_argument("--data", help="Тестовые данные JSON/YAML/TOML")
    p.add_argument("--json", action="store_true", help="Вывод в JSON")

    p = sub.add_parser("convert-file", help="Универсальная конвертация одного документа")
    p.add_argument("input", help="Входной файл")
    p.add_argument("output", help="Выходной файл или каталог")
    formats = ["pdf", "docx", "pptx", "html", "latex", "model", "txt", "djvu", "epub"]
    p.add_argument("--source-format", choices=formats, help="Формат входа, если его нельзя определить по расширению")
    p.add_argument("--target-format", choices=formats, help="Формат выхода, если его нельзя определить по расширению")
    p.add_argument("--mode", choices=["editable", "faithful", "balanced"], default="balanced")
    p.add_argument(
        "--feature",
        action="append",
        choices=[
            "text",
            "styles",
            "raster_images",
            "vector_graphics",
            "formulas",
            "tables",
            "page_geometry",
            "sections",
            "running_content",
            "notes",
            "fields",
        ],
        help="Приоритетная функция документа; можно повторять",
    )
    p.add_argument("--max-steps", type=int, default=4)
    p.add_argument("--max-loss-issues", type=int, help="Максимум диагностированных потерь; 0 запрещает любые LOSS")
    text_check = p.add_mutually_exclusive_group()
    text_check.add_argument(
        "--require-unchanged-text", action="store_true", help="Требовать точного сохранения текста исходных абзацев",
    )
    text_check.add_argument("--text-preservation", choices=["paragraphs", "flow"], help="Режим проверки сохранности текста")
    p.add_argument(
        "--max-text-edits", type=int, help="Допуск вставок, удалений и замен слов; включает проверку последовательности",
    )
    p.add_argument(
        "--max-lost-objects", type=int,
        help="Максимум объектов без совпадения, включая вложенные; непроверяемый бюджет блокирует результат",
    )
    p.add_argument("--json", action="store_true", help="Вывод в JSON")

    p = sub.add_parser("inspect", help="Проверить структуру и качество DOCX, PDF или JSON-модели")
    p.add_argument("input", help="Путь к DOCX, PDF или JSON-модели")
    p.add_argument("--compare", help="Сравнить структуру с другим DOCX, PDF или JSON-моделью")
    p.add_argument("-o", "--output", help="Сохранить JSON-отчёт в файл")
    p.add_argument("--strict", action="store_true", help="Возвращать ошибку при предупреждениях")
    p.add_argument("--json", action="store_true", help="Вывод в JSON")

    p = sub.add_parser("plan", help="Подобрать маршрут конвертации и оценить ожидаемые потери")
    formats = ["pdf", "docx", "pptx", "html", "latex", "model", "txt", "djvu", "epub"]
    p.add_argument("source", choices=formats)
    p.add_argument("target", choices=formats)
    p.add_argument("--mode", choices=["editable", "faithful", "balanced"], default="balanced")
    p.add_argument(
        "--feature",
        action="append",
        choices=[
            "text",
            "styles",
            "raster_images",
            "vector_graphics",
            "formulas",
            "tables",
            "page_geometry",
            "sections",
            "running_content",
            "notes",
            "fields",
        ],
        help="Приоритетная функция документа; можно повторять",
    )
    p.add_argument("--max-steps", type=int, default=4)
    p.add_argument("--json", action="store_true", help="Вывод в JSON")

    p = sub.add_parser("recognize", help="OCR распознавание (печатный/рукописный текст)")
    p.add_argument("input", type=str, help="Путь к PDF или изображению")
    p.add_argument("--lang", default="rus+eng", help="Языки через + (rus+eng)")
    p.add_argument("--output", type=str, help="Выходной файл (.docx/.tex/.txt)")
    p.add_argument("--backend", choices=["auto", "tesseract", "easyocr", "paddle"], default="auto",
                   help="OCR движок")
    p.add_argument("--gpu", action="store_true", help="Использовать GPU (если доступен CUDA)")
    p.add_argument("--mode", choices=["printed", "handwriting"], default="printed",
                   help="Тип текста: printed (печатный) или handwriting (рукописный)")
    p.add_argument("--scenario", choices=["fast", "structure", "scan"], default="structure",
                   help="PDF: fast (только текстовый слой), structure (text layer + OCR), scan (только OCR)")
    p.add_argument("--scale", type=int, default=3, help="Масштаб рендеринга PDF (2-6)")
    p.add_argument("--output-format", choices=["txt", "docx", "tex"], default="txt",
                   help="Формат выходного файла (требуется --output)")
    p.add_argument("--json", action="store_true", help="Вывод в JSON")

    p = sub.add_parser("bibtex", help="Генерация .bib из PDF")
    p.add_argument("-s", "--source", default="./literature_files")
    p.add_argument("-o", "--output", default="bibliography.bib")
    p.add_argument("--json", action="store_true", help="Вывод в JSON")

    p = sub.add_parser("init", help="Создать конфигурационный файл")
    p.add_argument("-o", "--output", default="config.json")

    p = sub.add_parser("web", help="Запуск веб-интерфейса")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", type=str, default="127.0.0.1")

    p = sub.add_parser("run", help="Запуск конвейера по YAML/TOML-файлу")
    p.add_argument("pipeline", nargs="?", default=None,
                   help="Путь к .yaml/.yml/.toml/.json (не нужен с --list)")
    p.add_argument("--json", action="store_true", help="Вывести результат как JSON")
    p.add_argument("--list", action="store_true", help="Показать доступные операции и выйти")

    p = sub.add_parser("completion", help="Скрипт автодополнения для оболочки")
    p.add_argument("shell", choices=["bash", "zsh", "fish"],
                   help="Оболочка: bash/zsh/fish")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = _setup_parser()
    args = parser.parse_args(argv)

    debug = bool(getattr(args, "debug", False))
    configure_logging(debug=debug)

    if not args.command:
        parser.print_help()
        return 1

    try:
        match args.command:
            case "extract":
                return cmd_extract(args)
            case "convert":
                return cmd_convert(args)
            case "convert-file":
                return cmd_convert_file(args)
            case "pptx2html":
                return cmd_pptx2html(args)
            case "match":
                return cmd_match(args)
            case "gost":
                return cmd_gost(args)
            case "stats":
                return cmd_stats(args)
            case "export":
                return cmd_export(args)
            case "generate":
                return cmd_generate(args)
            case "template-check":
                return cmd_template_check(args)
            case "inspect":
                return cmd_inspect(args)
            case "plan":
                return cmd_plan(args)
            case "recognize":
                return cmd_recognize(args)
            case "bibtex":
                return cmd_bibtex(args)
            case "init":
                return cmd_init(args)
            case "web":
                return cmd_web(args)
            case "run":
                return cmd_run(args)
            case "completion":
                return cmd_completion(args)
            case _:
                parser.print_help()
                return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        logger.exception("Command failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
