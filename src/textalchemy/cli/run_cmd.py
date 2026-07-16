import argparse
import json
import sys


def cmd_run(args: argparse.Namespace) -> int:
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
