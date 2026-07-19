"""Shell completion скрипты (bash/zsh/fish)."""
from __future__ import annotations

import argparse


def _discover_commands() -> list[str]:
    """Получить список подкоманд из основного парсера (без дублирования)."""
    from textalchemy.__main__ import _setup_parser

    parser = _setup_parser()
    sub = parser._subparsers  # type: ignore[attr-defined]
    if not sub:
        return []
    # Первая (и единственная) группа subparsers.
    actions = sub._group_actions[0]  # type: ignore[attr-defined]
    return sorted(actions.choices.keys())


def cmd_completion(args: argparse.Namespace) -> int:
    shell = args.shell
    prog = "textalchemy"
    commands = _discover_commands()
    if shell == "bash":
        print(_bash_completion(prog, commands))
    elif shell == "zsh":
        print(_zsh_completion(prog, commands))
    elif shell == "fish":
        print(_fish_completion(prog, commands))
    else:
        print(f"Unknown shell: {shell}", file=__import__("sys").stderr)
        return 1
    return 0


def _bash_completion(prog: str, commands: list[str]) -> str:
    cmds = " ".join(commands)
    return f"""# {prog} bash completion
_{prog}_completion() {{
    local cur=${{COMP_WORDS[COMP_CWORD]}}
    local prev=${{COMP_WORDS[COMP_CWORD-1]}}
    if [ $COMP_CWORD -eq 1 ]; then
        COMPREPLY=( $(compgen -W "{cmds}" -- "$cur") )
    fi
}}
complete -F _{prog}_completion {prog}
"""


def _zsh_completion(prog: str, commands: list[str]) -> str:
    cmds = " ".join(commands)
    return f"""#compdef {prog}
_{prog}_completion() {{
    local -a cmds
    cmds=({cmds})
    _describe '{prog} commands' cmds
}}
_{prog}_completion "$@"
"""


def _fish_completion(prog: str, commands: list[str]) -> str:
    cmds = " ".join(commands)
    return f"""# {prog} fish completion
complete -c {prog} -f -n '__fish_use_subcommand' -a "{cmds}"
"""


__all__ = ["cmd_completion"]
