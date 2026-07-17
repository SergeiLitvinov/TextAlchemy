import argparse
import json
import sys
from pathlib import Path


def cmd_gost(args: argparse.Namespace) -> int:
    from textalchemy.pipeline.bibliography import parse_bibliography
    from textalchemy.pipeline.render import render_gost

    items = parse_bibliography(path=args.input)
    result = render_gost(items=items)
    Path(args.output).write_text(result, encoding="utf-8")
    if args.json:
        print(json.dumps({"input": args.input, "output": args.output, "entries": len(items)}))
    else:
        print(f"Saved: {args.output} ({len(items)} entries)")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    from textalchemy.organize.bibliography import BibliographyParser
    source = Path(args.source)
    output = Path(args.output)
    bib_items = []
    if args.bibliography:
        bib_items = BibliographyParser.parse_file(args.bibliography)
    total = len([f for f in source.rglob("*") if f.is_file()]) if source.exists() else 0
    matched = len([f for f in output.rglob("*") if f.is_file()]) if output.exists() else 0
    progress = matched / len(bib_items) * 100 if bib_items else None
    if args.json:
        print(json.dumps({
            "total": total, "matched": matched,
            "unmatched": total - matched,
            "bibliography": len(bib_items),
            "progress": round(progress, 1) if progress is not None else None,
        }))
    else:
        print("Statistics:")
        print(f"  Total files: {total}")
        print(f"  Matched: {matched}")
        print(f"  Unmatched: {total - matched}")
        print(f"  Bibliography: {len(bib_items)} entries")
        if bib_items:
            print(f"  Progress: {progress:.1f}%")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
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
