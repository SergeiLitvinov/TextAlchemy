from pathlib import Path

from textalchemy.core.exceptions import ExtractError
from textalchemy.core.io import atomic_write_text


def extract_text(input_path: str | Path, output_path: str | Path | None = None) -> str:
    from textalchemy.formats.docx import read_docx

    input_path = Path(input_path)
    if not input_path.exists():
        raise ExtractError(f"File not found: {input_path}")
    if input_path.suffix.lower() not in (".docx",):
        raise ExtractError(f"Unsupported format: {input_path.suffix}")
    try:
        result = read_docx(input_path)
        text = result.plain
    except Exception as e:
        raise ExtractError(f"Failed to extract text: {e}") from e
    if output_path:
        atomic_write_text(output_path, text, encoding="utf-8")
    return text


def extract_text_with_tables(input_path: str | Path, output_path: str | Path | None = None) -> str:
    from textalchemy.formats.docx import read_docx

    input_path = Path(input_path)
    if not input_path.exists():
        raise ExtractError(f"File not found: {input_path}")
    try:
        result = read_docx(input_path, include_tables=True)
        text = result.plain
    except Exception as e:
        raise ExtractError(f"Failed to extract text: {e}") from e
    if output_path:
        atomic_write_text(output_path, text, encoding="utf-8")
    return text
