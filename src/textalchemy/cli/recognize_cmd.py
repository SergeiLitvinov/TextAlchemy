import argparse
import json
import sys
from pathlib import Path


def cmd_recognize(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if not input_path.exists():
        if args.json:
            print(json.dumps({"error": f"file not found: {args.input}"}))
        else:
            print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1

    from textalchemy.recognize import OcrEngine
    engine = OcrEngine(languages=args.lang.split("+"), use_gpu=args.gpu, backend=args.backend)

    ext = input_path.suffix.lower()

    # Изображения всегда требуют OCR; PDF — только если сценарий не fast.
    needs_ocr = ext != ".pdf" or args.scenario in ("structure", "scan")
    if needs_ocr and not engine.is_available:
        if args.json:
            print(json.dumps({"error": "OCR backend not available", "backend": engine.backend_name}))
        else:
            print(f"[STUB] OCR for: {args.input}")
            print(f"[STUB] Backend: {engine.backend_name}")
            print("[STUB] Install pytesseract, easyocr or paddleocr")
        return 1

    handwriting = args.mode == "handwriting"

    if ext == ".pdf":
        from textalchemy.formats.pdf_ocr_merge import read_pdf_scenario

        result = read_pdf_scenario(
            args.input,
            mode=args.scenario,
            ocr_engine=engine,
            scale=args.scale,
            handwriting=handwriting,
        )
        text = result.plain
        pages = result.pages
    else:
        result = engine.recognize(args.input, handwriting=handwriting)
        text = result.text
        pages = 1

    if args.output:
        out_path = Path(args.output)
        fmt = out_path.suffix.lower().lstrip(".") or args.output_format
        if fmt == "docx":
            from docx import Document as DocxDocument
            docx = DocxDocument()
            for paragraph in text.split("\n\n"):
                if paragraph.strip():
                    docx.add_paragraph(paragraph.strip())
            docx.save(str(out_path))
        elif fmt == "tex":
            from textalchemy.core.latex import escape_latex
            latex = (
                "\\documentclass[12pt,a4paper]{article}\n"
                "\\usepackage[T2A]{fontenc}\n"
                "\\usepackage[utf8]{inputenc}\n"
                "\\usepackage[russian]{babel}\n"
                "\\usepackage{geometry}\n"
                "\\geometry{top=2cm,bottom=2cm,left=2cm,right=2cm}\n\n"
                "\\begin{document}\n\n"
                f"{escape_latex(text)}\n\n"
                "\\end{document}\n"
            )
            out_path.write_text(latex, encoding="utf-8")
        else:
            out_path.write_text(text, encoding="utf-8")
        if args.json:
            print(json.dumps({"saved": str(out_path), "pages": pages, "length": len(text)}))
        else:
            print(f"Saved: {out_path}")
    else:
        if args.json:
            print(json.dumps({"text": text, "pages": pages, "length": len(text)}, ensure_ascii=False))
        else:
            print(text)
    return 0
