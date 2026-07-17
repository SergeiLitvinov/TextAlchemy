"""Shell completion скрипты (bash/zsh/fish)."""
from __future__ import annotations

import argparse

_COMMANDS = [
    "extract", "convert", "pptx2html", "match", "gost", "stats",
    "export", "generate", "recognize", "bibtex", "init", "web", "run",
]


def cmd_completion(args: argparse.Namespace) -> int:
    shell = args.shell
    prog = "textalchemy"
    if shell == "bash":
        print(_bash_completion(prog))
    elif shell == "zsh":
        print(_zsh_completion(prog))
    elif shell == "fish":
        print(_fish_completion(prog))
    else:
        print(f"Unknown shell: {shell}", file=__import__("sys").stderr)
        return 1
    return 0


def _bash_completion(prog: str) -> str:
    cmds = " ".join(_COMMANDS)
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


def _zsh_completion(prog: str) -> str:
    cmds = " ".join(_COMMANDS)
    return f"""#compdef {prog}
_{prog}_completion() {{
    local -a cmds
    cmds=({cmds})
    _describe '{prog} commands' cmds
}}
_{prog}_completion "$@"
"""


def _fish_completion(prog: str) -> str:
    cmds = " ".join(_COMMANDS)
    return f"""# {prog} fish completion
complete -c {prog} -f -n '__fish_use_subcommand' -a "{cmds}"
"""


__all__ = ["cmd_completion"]
