import argparse


def cmd_init(args: argparse.Namespace) -> int:
    from textalchemy.core.config import generate_default_config
    config = generate_default_config()
    config.save(args.output)
    print(f"Config saved: {args.output}")
    print("Это шаблон Config для Python API. CLI не применяет его через --config; используйте параметры команды или run.")
    return 0
