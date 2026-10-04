from opendoc_formats.errors import ConvertError as ConvertError
from opendoc_formats.errors import ExtractError as ExtractError
from opendoc_formats.errors import FormatError as TextAlchemyError


class ConfigError(TextAlchemyError):
    """Configuration-related errors."""


class OrganizeError(TextAlchemyError):
    """Library organization errors."""


class GenerateError(TextAlchemyError):
    """Document generation errors."""


class RecognizeError(TextAlchemyError):
    """Visual recognition errors."""
