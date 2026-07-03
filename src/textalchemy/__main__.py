import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("textalchemy")

# Гарантируем UTF-8 для stdout/stderr на Windows (cp1251 иначе не вывозит '→').
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass


def _eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def _setup_parser():
    parser = argparse.ArgumentParser(
        prog="textalchemy",
        description="TextAlchemy — универсальный инструментарий обработки документов",
    )
    parser.add_argument("--version", action="version",
                        version=f"TextAlchemy {__import__('textalchemy').__version__}")
    parser.add_argument("-c", "--config", help="Путь к конфигурационному файлу JSON")

    sub = parser.add_subparsers(dest="command", help="Команды")

    p = sub.add_parser("extract", help="Извлечение текста/LaTeX из DOCX")
    p.add_argument("input", type=str, help="Входной DOCX файл")
    p.add_argument("output", type=str, nargs="?", help="Выходной файл")
    p.add_argument("--format", choices=["text", "latex", "pandoc"], default="text")
    p.add_argument("--doc-type", choices=["manuscript", "abstract"], default="manuscript")

    p = sub.add_parser("convert", help="Конвертация PDF в DOCX")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output")
    p.add_argument("--tool", choices=["pdf2docx", "pymupdf", "libreoffice", "fanout"], default="fanout")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("pptx2html", help="Конвертация .pptx в автономный HTML-просмотрщик")
    p.add_argument("-i", "--input", required=True, help="Путь к .pptx файлу")
    p.add_argument("-o", "--output", required=True, help="Директория для HTML-результата")
    p.add_argument("--no-assets", action="store_true", help="Не копировать встроенные css/js (если они уже есть)")

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

    p = sub.add_parser("stats", help="Статистика библиотеки")
    p.add_argument("-s", "--source", default="./literature_files")
    p.add_argument("-o", "--output", default="./renamed")
    p.add_argument("-b", "--bibliography")

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

    p = sub.add_parser("recognize", help="OCR распознавание")
    p.add_argument("input", type=str)
    p.add_argument("--lang", default="rus+eng")
    p.add_argument("--output", type=str)
    p.add_argument("--backend", choices=["auto", "tesseract", "easyocr"], default="auto")

    p = sub.add_parser("bibtex", help="Генерация .bib из PDF")
    p.add_argument("-s", "--source", default="./literature_files")
    p.add_argument("-o", "--output", default="bibliography.bib")

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

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = _setup_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    try:
        match args.command:
            case "extract":
                return _cmd_extract(args)
            case "convert":
                return _cmd_convert(args)
            case "pptx2html":
                return _cmd_pptx2html(args)
            case "match":
                return _cmd_match(args)
            case "gost":
                return _cmd_gost(args)
            case "stats":
                return _cmd_stats(args)
            case "export":
                return _cmd_export(args)
            case "generate":
                return _cmd_generate(args)
            case "recognize":
                return _cmd_recognize(args)
            case "bibtex":
                return _cmd_bibtex(args)
            case "init":
                return _cmd_init(args)
            case "web":
                return _cmd_web(args)
            case "run":
                return _cmd_run(args)
            case _:
                parser.print_help()
                return 1
    except Exception as e:
        _eprint(f"Error: {e}")
        logger.exception("Command failed")
        return 1


def _cmd_extract(args: argparse.Namespace) -> int:
    from textalchemy.extract import docx_to_latex, docx_to_latex_pandoc, extract_text
    if args.format == "latex":
        result = docx_to_latex(args.input, args.output, args.doc_type)
    elif args.format == "pandoc":
        result = docx_to_latex_pandoc(args.input, args.output, args.doc_type)
    else:
        result = extract_text(args.input, args.output)
    if args.output:
        print(f"Saved: {args.output}")
    else:
        print(result)
    return 0


def _cmd_convert(args: argparse.Namespace) -> int:
    from tqdm import tqdm

    from textalchemy.convert import create_converter
    input_dir = Path(args.input)
    if not input_dir.is_dir():
        print(f"Error: {args.input} is not a directory")
        return 1
    output_dir = Path(args.output) if args.output else input_dir / "converted"
    converter = create_converter(args.tool)
    pdf_files = sorted(input_dir.rglob("*.pdf"))
    if not pdf_files:
        print("No PDF files found")
        return 0
    if args.dry_run:
        print(f"Found {len(pdf_files)} PDF files:")
        for f in pdf_files:
            print(f"  {f}")
        return 0
    success = 0
    failed = 0
    for pdf_path in tqdm(pdf_files, desc="Converting"):
        rel = pdf_path.relative_to(input_dir)
        out_path = output_dir / rel.with_suffix(".docx")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = converter.convert(pdf_path, out_path)
        if result.success:
            success += 1
        else:
            failed += 1
    print(f"\nDone: {success} converted, {failed} failed")
    return 0 if failed == 0 else 1


def _cmd_pptx2html(args: argparse.Namespace) -> int:
    from textalchemy.convert.pptx_to_html import PptxToHtmlConverter
    converter = PptxToHtmlConverter(copy_assets=not args.no_assets)
    result = converter.convert(args.input, args.output)
    if result.success:
        print(f"OK: {result.output_path}")
        return 0
    print(f"Error: {result.error}", file=sys.stderr)
    return 1


def _cmd_match(args: argparse.Namespace) -> int:
    """Сопоставить файлы с библиографией через pipeline.

    Использует ``match.files`` (pipeline). Внутри — extract.text + match.bibliography + name.from_match.
    """
    from textalchemy.organize import load_manual_matches
    from textalchemy.pipeline.bibliography import parse_bibliography
    from textalchemy.pipeline.match_files import match_files

    bib_path = args.bibliography
    if not bib_path:
        candidates = list(Path(".").glob("*bibliography*"))
        if not candidates:
            print("Error: no bibliography file found. Use -b.")
            return 1
        bib_path = str(candidates[0])

    items = parse_bibliography(path=bib_path)
    manual = load_manual_matches()
    print(f"Loaded {len(items)} entries, {len(manual)} manual matches")

    source_dir = Path(args.source)
    if not source_dir.is_dir():
        print(f"Error: {args.source} is not a directory")
        return 1

    if args.dry_run:
        ext_map = {".pdf", ".docx", ".djvu", ".txt"}
        n = sum(1 for f in source_dir.rglob("*") if f.is_file() and f.suffix.lower() in ext_map)
        print(f"Found {n} files, {len(items)} bibliography entries")
        return 0

    output_dir = Path(args.output) if not args.dry_run else None
    matches = match_files(
        source=source_dir,
        items=items,
        threshold=args.threshold,
        manual=manual,
        output_dir=output_dir,
        copy=not args.dry_run,
    )

    matched = [m for m in matches if m.matched]
    unmatched = [m for m in matches if not m.matched]
    print(f"\nMatched: {len(matched)}, Unmatched: {len(unmatched)}")

    if args.json:
        report = {
            "matched": [
                {
                    "original": m.document.path.name,
                    "new": (output_dir / m.document.path.name if output_dir else m.document.path.name),
                    "score": round(m.score, 2),
                    "signals": [
                        {"name": s.name, "score": s.score, "weight": s.weight}
                        for s in m.signals if s.score > 0
                    ],
                }
                for m in matched
            ],
            "unmatched": [m.document.path.name for m in unmatched],
        }
        Path("matching_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print("Report saved: matching_report.json")
    return 0


def _cmd_gost(args: argparse.Namespace) -> int:
    """Библиография → ГОСТ через pipeline: bibliography.parse → render.gost."""
    from textalchemy.pipeline.bibliography import parse_bibliography
    from textalchemy.pipeline.render import render_gost

    items = parse_bibliography(path=args.input)
    result = render_gost(items=items)
    Path(args.output).write_text(result, encoding="utf-8")
    print(f"Saved: {args.output} ({len(items)} entries)")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    """Статистика библиотеки (без изменений — не извлекает документы, проходит по FS)."""
    from textalchemy.organize.bibliography import BibliographyParser
    source = Path(args.source)
    output = Path(args.output)
    bib_items = []
    if args.bibliography:
        bib_items = BibliographyParser.parse_file(args.bibliography)
    total = len([f for f in source.rglob("*") if f.is_file()]) if source.exists() else 0
    matched = len([f for f in output.rglob("*") if f.is_file()]) if output.exists() else 0
    print("Statistics:")
    print(f"  Total files: {total}")
    print(f"  Matched: {matched}")
    print(f"  Unmatched: {total - matched}")
    print(f"  Bibliography: {len(bib_items)} entries")
    if bib_items:
        print(f"  Progress: {matched / len(bib_items) * 100:.1f}%")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    """Экспорт библиографии через pipeline: bibliography.parse → render.*."""
    from textalchemy.pipeline.bibliography import parse_bibliography
    from textalchemy.pipeline.render import render_gost, render_json, render_markdown

    items = parse_bibliography(path=args.input)
    fmt = args.format
    if fmt == "json":
        out = args.output or "bibliography.json"
        Path(out).write_text(render_json(items=items), encoding="utf-8")
    elif fmt == "markdown":
        out = args.output or "bibliography.md"
        Path(out).write_text(render_markdown(items=items), encoding="utf-8")
    elif fmt == "gost":
        out = args.output or "bibliography_gost.txt"
        Path(out).write_text(render_gost(items=items), encoding="utf-8")
    else:
        print(f"Unknown format: {fmt}", file=sys.stderr)
        return 1
    print(f"Exported: {out}")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    from textalchemy.generate import generate_document, list_templates
    if args.list:
        templates = list_templates(args.templates_dir)
        if not templates:
            print("No templates found")
        else:
            for t in templates:
                print(f"  {t.name} — {t.description}")
        return 0
    params = {}
    if args.param:
        for p in args.param:
            if "=" in p:
                k, v = p.split("=", 1)
                params[k] = v
    result = generate_document(args.template, args.output, params, args.templates_dir)
    print(f"Generated: {result}")
    return 0


def _cmd_recognize(args: argparse.Namespace) -> int:
    from textalchemy.recognize import OcrEngine
    engine = OcrEngine(languages=args.lang.split("+"))
    if not engine.is_available:
        text = f"[STUB] OCR for: {args.input}\n[STUB] Backend: {engine.backend_name}\n[STUB] Install pytesseract or easyocr"
    else:
        text = engine.recognize(args.input).text
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Saved: {args.output}")
    else:
        print(text)
    return 0


def _cmd_bibtex(args: argparse.Namespace) -> int:
    """Генерация .bib через pipeline: извлечь имена из PDF (legacy) или парсить bib-файл."""
    from textalchemy.organize.bibtex import generate_bib
    bib = generate_bib(args.source, args.output)
    count = bib.count("@misc{")
    print(f"Generated {count} BibTeX entries")
    if args.output:
        print(f"Saved: {args.output}")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    from textalchemy.core.config import generate_default_config
    config = generate_default_config()
    config.save(args.output)
    print(f"Config saved: {args.output}")
    return 0


def _cmd_web(args) -> int:
    import uvicorn

    from textalchemy.web import app
    print(f"Starting TextAlchemy web at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from textalchemy.core.registry import all_operations
    from textalchemy.pipeline.runner import run_pipeline

    if args.list:
        print("Available operations:")
        for s in all_operations():
            print(f"  {s.id:30s}  {s.description}")
        return 0

    if not args.pipeline:
        print("Error: pipeline path required (or use --list)", file=sys.stderr)
        return 1

    result = run_pipeline(args.pipeline)
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        for sr in result.steps:
            mark = "OK" if not sr.error else "FAIL"
            print(f"  [{mark}] {sr.op} -> {sr.name}")
            if sr.error:
                print(f"         {sr.error}")
        if result.ok:
            print(f"Final: {_repr(result.final)}")
        else:
            print(f"Error: {result.error}")
    return 0 if result.ok else 1


def _repr(v: object) -> str:
    if v is None:
        return "None"
    if isinstance(v, str):
        return v[:120] + ("…" if len(v) > 120 else "")
    return str(v)


if __name__ == "__main__":
    sys.exit(main())
