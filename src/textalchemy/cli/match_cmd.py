import argparse
import json
from pathlib import Path


def cmd_match(args: argparse.Namespace) -> int:
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
