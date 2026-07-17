import argparse


def cmd_init(args: argparse.Namespace) -> int:
    from textalchemy.core.config import generate_default_config
    config = generate_default_config()
    config.save(args.output)
    print(f"Config saved: {args.output}")
    return 0
