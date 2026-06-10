class TextAlchemyError(Exception):
    """Base exception for all TextAlchemy errors."""


class ConfigError(TextAlchemyError):
    """Configuration-related errors."""


class ExtractError(TextAlchemyError):
    """Document extraction errors."""


class ConvertError(TextAlchemyError):
    """Document conversion errors."""


class OrganizeError(TextAlchemyError):
    """Library organization errors."""


class GenerateError(TextAlchemyError):
    """Document generation errors."""


class RecognizeError(TextAlchemyError):
    """Visual recognition errors."""
