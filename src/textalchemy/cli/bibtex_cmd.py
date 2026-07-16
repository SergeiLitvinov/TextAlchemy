import argparse
import json


def cmd_bibtex(args: argparse.Namespace) -> int:
    from textalchemy.organize.bibtex import generate_bib
    bib = generate_bib(args.source, args.output)
    count = bib.count("@misc{")
    if args.json:
        print(json.dumps({"source": args.source, "output": args.output, "entries": count}))
    else:
        print(f"Generated {count} BibTeX entries")
        if args.output:
            print(f"Saved: {args.output}")
    return 0
