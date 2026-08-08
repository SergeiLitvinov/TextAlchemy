"""Тесты централизованного логирования."""

from __future__ import annotations

import logging

from textalchemy.core.logging import PACKAGE_NAME, configure_logging, get_logger


def test_get_logger_keeps_package_namespace():
    assert get_logger("extract").name == "textalchemy.extract"
    assert get_logger("textalchemy.foo").name == "textalchemy.foo"
    assert get_logger("textalchemy").name == "textalchemy"


def test_get_logger_strips_dots():
    assert get_logger(".convert").name == "textalchemy.convert"


def test_configure_logging_sets_level(caplog):
    with caplog.at_level(logging.DEBUG):
        configure_logging(debug=True)
    root = logging.getLogger(PACKAGE_NAME)
    assert root.level == logging.DEBUG


def test_configure_logging_quiet(caplog):
    with caplog.at_level(logging.ERROR):
        configure_logging(quiet=True)
    root = logging.getLogger(PACKAGE_NAME)
    assert root.level == logging.ERROR


def test_configure_logging_default(caplog):
    with caplog.at_level(logging.WARNING):
        configure_logging(debug=False, quiet=False)
    root = logging.getLogger(PACKAGE_NAME)
    assert root.level == logging.WARNING
