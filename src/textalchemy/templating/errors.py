"""Errors belonging to the template engine, independent of application errors."""


class TemplateError(ValueError):
    """Invalid template, data or resource supplied to the engine."""
