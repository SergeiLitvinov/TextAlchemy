"""Базовые типы и утилиты ядра."""

from textalchemy.core.exceptions import (
    ConfigError,
    ConvertError,
    ExtractError,
    GenerateError,
    OrganizeError,
    RecognizeError,
    TextAlchemyError,
)
from textalchemy.core.hashing import compute_file_hash
from textalchemy.core.types import (
    BibItem,
    Block,
    BlockType,
    DocFormat,
    Document,
    Match,
    Signal,
    Table,
    Text,
)

__all__ = [
    "DocFormat",
    "BlockType",
    "Document",
    "Block",
    "Table",
    "Text",
    "BibItem",
    "Signal",
    "Match",
    "compute_file_hash",
    "TextAlchemyError",
    "ConfigError",
    "ExtractError",
    "ConvertError",
    "OrganizeError",
    "GenerateError",
    "RecognizeError",
]
