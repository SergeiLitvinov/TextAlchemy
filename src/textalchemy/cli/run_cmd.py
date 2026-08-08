import argparse
import json
import sys


def cmd_run(args: argparse.Namespace) -> int:
    from textalchemy.core.registry import all_operations
    from textalchemy.pipeline import register_builtin_operations
    from textalchemy.pipeline.runner import run_pipeline

    register_builtin_operations()

    if args.list:
        print("Available operations:")
        for s in all_operations():
            print(f"  {s.id:30s}  {s.description}")
        return 0

    if not args.pipeline:
        print("Error: pipeline path required (or use --list)", file=sys.stderr)
        return 1

    progress = None if args.json else _render_progress
    result = run_pipeline(args.pipeline, progress=progress)
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


def _render_progress(ev) -> None:
    """Напечатать событие прогресса в одну строку (без перевода каретки)."""
    if ev.kind == "step_start":
        print(f"\r[{ev.index + 1}/{ev.total}] {ev.op} ...", end="", flush=True)
    elif ev.kind == "step_done":
        print(f"\r[{ev.index + 1}/{ev.total}] {ev.op} OK ({ev.elapsed:.2f}s)")
    elif ev.kind == "step_failed":
        print(f"\r[{ev.index + 1}/{ev.total}] {ev.op} FAILED: {ev.error}")
    elif ev.kind == "pipeline_done" and ev.error:
        print(f"Error: {ev.error}")


def _repr(v: object) -> str:
    if v is None:
        return "None"
    if isinstance(v, str):
        return v[:120] + ("…" if len(v) > 120 else "")
    return str(v)
