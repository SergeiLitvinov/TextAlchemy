"""Refresh prose and references when MkDocs rebuilds during local preview."""

from tools.documentation.site import prepare


def on_pre_build(config):
    prepare()
