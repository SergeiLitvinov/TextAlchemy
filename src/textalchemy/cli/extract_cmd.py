import argparse
import json


def cmd_extract(args: argparse.Namespace) -> int:
    from textalchemy.extract import docx_to_latex, docx_to_latex_pandoc, extract_text
    if args.format == "latex":
        result = docx_to_latex(args.input, args.output, args.doc_type)
    elif args.format == "pandoc":
        result = docx_to_latex_pandoc(args.input, args.output, args.doc_type)
    else:
        result = extract_text(args.input, args.output)
    if args.output:
        if args.json:
            print(json.dumps({"saved": args.output, "format": args.format}, ensure_ascii=False))
        else:
            print(f"Saved: {args.output}")
    else:
        if args.json:
            print(json.dumps({"text": result, "format": args.format}, ensure_ascii=False))
        else:
            print(result)
    return 0
