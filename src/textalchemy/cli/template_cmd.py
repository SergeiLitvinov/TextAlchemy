"""CLI-проверка DOCX-шаблона без генерации результата."""

import argparse
import json


def cmd_template_check(args: argparse.Namespace) -> int:
    from textalchemy.formats.docx import read_docx_model
    from textalchemy.generate import (
        inspect_document_template,
        load_template_data,
        load_template_schema,
        render_document_template,
    )

    model = read_docx_model(args.template)
    schema = load_template_schema(args.schema) if args.schema else None
    inspection = inspect_document_template(model, schema)
    payload = inspection.to_dict()
    payload["template"] = args.template
    payload["schema"] = args.schema
    payload["data"] = args.data

    data_valid: bool | None = None
    if args.data:
        data = load_template_data(args.data)
        try:
            render_document_template(model, data, schema=schema)
            data_valid = True
        except Exception as error:  # noqa: BLE001 - CLI reports validation failures uniformly
            data_valid = False
            payload["errors"].append(str(error))
    payload["data_valid"] = data_valid
    payload["valid"] = not payload["errors"] and data_valid is not False

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        mark = "OK" if payload["valid"] else "FAIL"
        print(f"[{mark}] Template: {args.template}")
        variables = ", ".join(payload["required_variables"]) or "none"
        print(f"Required variables: {variables}")
        if data_valid is not None:
            print(f"Data: {'valid' if data_valid else 'invalid'}")
        for warning in payload["warnings"]:
            print(f"Warning: {warning}")
        for error in payload["errors"]:
            print(f"Error: {error}")
    return 0 if payload["valid"] else 1


__all__ = ["cmd_template_check"]
