import argparse
import json
import sys
from pathlib import Path


def cmd_convert(args: argparse.Namespace) -> int:
    from tqdm import tqdm

    from textalchemy.convert import create_converter
    input_dir = Path(args.input)
    if not input_dir.is_dir():
        if args.json:
            print(json.dumps({"error": f"{args.input} is not a directory"}))
        else:
            print(f"Error: {args.input} is not a directory")
        return 1
    output_dir = Path(args.output) if args.output else input_dir / "converted"
    converter = create_converter(args.tool)
    pdf_files = sorted(input_dir.rglob("*.pdf"))
    if not pdf_files:
        if args.json:
            print(json.dumps({"files": [], "success": 0, "failed": 0}))
        else:
            print("No PDF files found")
        return 0
    if args.dry_run:
        files = [str(f) for f in pdf_files]
        if args.json:
            print(json.dumps({"files": files, "dry_run": True}))
        else:
            print(f"Found {len(pdf_files)} PDF files:")
            for f in pdf_files:
                print(f"  {f}")
        return 0
    success = 0
    failed = 0
    results = []
    for pdf_path in tqdm(pdf_files, desc="Converting"):
        rel = pdf_path.relative_to(input_dir)
        out_path = output_dir / rel.with_suffix(".docx")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = converter.convert(pdf_path, out_path)
        results.append({"input": str(pdf_path), "output": str(out_path), "success": result.success})
        if result.success:
            success += 1
        else:
            failed += 1
    if args.json:
        print(json.dumps({"files": results, "success": success, "failed": failed}, ensure_ascii=False))
    else:
        print(f"\nDone: {success} converted, {failed} failed")
    return 0 if failed == 0 else 1


def cmd_pptx2html(args: argparse.Namespace) -> int:
    from textalchemy.pipeline.ingest import ingest_file
    from textalchemy.pipeline.render_html import render_html_pptx

    doc = ingest_file(path=args.input)
    result = render_html_pptx(doc=doc, output_dir=args.output, copy_assets=not args.no_assets)
    if result.success:
        if args.json:
            print(json.dumps({"success": True, "output_path": str(result.output_path)}))
        else:
            print(f"OK: {result.output_path}")
        return 0
    if args.json:
        print(json.dumps({"success": False, "error": result.error}))
    else:
        print(f"Error: {result.error}", file=sys.stderr)
    return 1
