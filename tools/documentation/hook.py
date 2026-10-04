"""Refresh prose and references when MkDocs rebuilds during local preview."""

import tomllib

from tools.documentation.site import ROOT, prepare


def on_pre_build(config):
    prepare()
    config.extra["app_version"] = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
