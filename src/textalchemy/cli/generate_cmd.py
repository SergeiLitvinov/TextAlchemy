import argparse
import json
from pathlib import Path


def cmd_generate(args: argparse.Namespace) -> int:
    from textalchemy.core.exceptions import GenerateError
    from textalchemy.generate import (
        TemplateEngine,
        generate_document,
        generate_docx_template,
        generate_html_template,
        generate_pdf_template,
        list_templates,
        load_template_data,
        load_template_schema,
    )

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
    if not args.template or not args.output:
        message = "template and output are required (or use --list)"
        if args.json:
            print(json.dumps({"success": False, "error": message}))
        else:
            print(f"Error: {message}")
        return 1

    try:
        params = load_template_data(args.data) if args.data else {}
        if args.param:
            for parameter in args.param:
                if "=" in parameter:
                    key, value = parameter.split("=", 1)
                    try:
                        params[key] = json.loads(value)
                    except json.JSONDecodeError:
                        params[key] = value

        engine = TemplateEngine(args.templates_dir)
        template_path = engine.resolve_template(args.template)
        if template_path.suffix.lower() == ".docx":
            schema = load_template_schema(args.schema) if args.schema else None
            output_suffix = Path(args.output).suffix.lower()
            generators = {
                ".docx": generate_docx_template,
                ".html": generate_html_template,
                ".htm": generate_html_template,
                ".pdf": generate_pdf_template,
            }
            generator = generators.get(output_suffix)
            if generator is None:
                raise GenerateError(f"Unsupported output format for DOCX template: {output_suffix or '<none>'}")
            report = generator(template_path, args.output, params, schema=schema, strict=not args.no_strict)
            payload = report.to_dict()
            payload["template"] = str(template_path)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"Generated: {report.output_path}")
                print(f"Quality: {'no reported losses' if report.lossless else 'with reported losses'}")
                for issue in report.issues:
                    place = f" ({issue.location})" if issue.location else ""
                    print(f"  {issue.severity.value}: {issue.message}{place}")
            return 0 if report.success else 1

        result = generate_document(str(template_path), args.output, params, args.templates_dir)
        if args.json:
            print(
                json.dumps(
                    {"success": True, "template": str(template_path), "output": args.output, "result": str(result)}
                )
            )
        else:
            print(f"Generated: {result}")
        return 0
    except Exception as error:  # noqa: BLE001 - CLI boundary must preserve valid JSON errors
        if args.json:
            print(json.dumps({"success": False, "error": str(error)}, ensure_ascii=False))
        else:
            print(f"Error: {error}")
        return 1
