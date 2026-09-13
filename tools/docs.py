"""Documentation entry point: uv run python -m tools.docs <command>."""

import argparse
import subprocess
import sys

from tools.documentation.generated import ROOT, sync
from tools.documentation.site import prepare


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build and check TextAlchemy documentation")
    parser.add_argument("command", choices=["generate", "check", "build", "serve"])
    parser.add_argument("--address", default="127.0.0.1:8001", help="Local documentation preview address")
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            print("Updated:", ", ".join(sync()) or "already current")
            return 0
        if args.command in {"build", "check"}:
            sync(check=True)
        if args.command == "check":
            from tools.documentation.checks import check

            check()
        print(f"Preparing {prepare()} documentation pages", flush=True)
        command = ["serve", "--dev-addr", args.address] if args.command == "serve" else ["build", "--strict"]
        return subprocess.call([sys.executable, "-m", "mkdocs", *command], cwd=ROOT)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
