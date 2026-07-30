from textalchemy.cli.bibliography_cmd import cmd_export, cmd_gost, cmd_stats
from textalchemy.cli.bibtex_cmd import cmd_bibtex
from textalchemy.cli.completion_cmd import cmd_completion
from textalchemy.cli.convert_cmd import cmd_convert, cmd_pptx2html
from textalchemy.cli.convert_file_cmd import cmd_convert_file
from textalchemy.cli.extract_cmd import cmd_extract
from textalchemy.cli.generate_cmd import cmd_generate
from textalchemy.cli.init_cmd import cmd_init
from textalchemy.cli.inspect_cmd import cmd_inspect
from textalchemy.cli.match_cmd import cmd_match
from textalchemy.cli.plan_cmd import cmd_plan
from textalchemy.cli.recognize_cmd import cmd_recognize
from textalchemy.cli.run_cmd import cmd_run
from textalchemy.cli.template_cmd import cmd_template_check
from textalchemy.cli.web_cmd import cmd_web

__all__ = [
    "cmd_extract", "cmd_convert", "cmd_convert_file", "cmd_pptx2html", "cmd_match", "cmd_plan",
    "cmd_gost", "cmd_stats", "cmd_export", "cmd_generate",
    "cmd_recognize", "cmd_bibtex", "cmd_init", "cmd_web", "cmd_run",
    "cmd_completion",
    "cmd_template_check",
    "cmd_inspect",
]
