import argparse
import json


def cmd_generate(args: argparse.Namespace) -> int:
    from textalchemy.generate import generate_document, list_templates
    if args.list:
        templates = list_templates(args.templates_dir)
        if args.json:
            data = [{"name": t.name, "description": t.description} for t in templates]
            print(json.dumps(data, ensure_ascii=False))
        elif not templates:
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
    if args.json:
        print(json.dumps({"template": args.template, "output": args.output, "result": result}))
    else:
        print(f"Generated: {result}")
    return 0
