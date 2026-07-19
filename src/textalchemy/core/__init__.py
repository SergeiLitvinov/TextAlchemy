"""Базовые типы и утилиты ядра."""
from textalchemy.core.doc_types import DOC_TYPE_KEYWORDS, DOC_TYPES
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
    OperationResult,
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
    "OperationResult",
    "compute_file_hash",
    "DOC_TYPES",
    "DOC_TYPE_KEYWORDS",
    "TextAlchemyError",
    "ConfigError",
    "ExtractError",
    "ConvertError",
    "OrganizeError",
    "GenerateError",
    "RecognizeError",
]
