"""TXT и DjVu → Text."""
from __future__ import annotations

from pathlib import Path
from typing import Union

from textalchemy.core.document_model import DocumentModel, Paragraph, Section, TextRun
from textalchemy.core.types import Block, BlockType, DocFormat, Text


def read_txt(path: Union[str, Path]) -> Text:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    try:
        text = p.read_text(encoding="utf-8")
        enc = "utf-8"
    except UnicodeDecodeError:
        text = p.read_text(encoding="cp1251")
        enc = "cp1251"
    return Text(
        blocks=[Block(type=BlockType.PARAGRAPH, text=text)],
        plain=text,
        source_format=DocFormat.TXT,
        engine=enc,
    )


def read_txt_model(path: Union[str, Path]) -> DocumentModel:
    """Импортировать строки TXT как редактируемые абзацы, включая пустые строки."""
    text = read_txt(path)
    normalized = text.plain.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [Paragraph(content=[TextRun(line)]) for line in normalized.split("\n")]
    return DocumentModel(
        source_format="txt",
        sections=[Section(blocks=paragraphs)],
        metadata={"engine": text.engine, "source_name": Path(path).name, "txt": {"line_separator": "\n"}},
    )


def read_djvu(path: Union[str, Path]) -> Text:
    import subprocess

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    try:
        result = subprocess.run(
            ["djvutxt", str(p)],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return Text(
            source_format=DocFormat.DJVU,
            engine="djvutxt",
            warnings=["djvutxt not found in PATH"],
        )
    except subprocess.TimeoutExpired:
        return Text(
            source_format=DocFormat.DJVU,
            engine="djvutxt",
            warnings=["djvutxt timeout"],
        )
    if result.returncode != 0:
        return Text(
            source_format=DocFormat.DJVU,
            engine="djvutxt",
            warnings=[f"djvutxt rc={result.returncode}"],
        )
    text = result.stdout
    return Text(
        blocks=[Block(type=BlockType.PARAGRAPH, text=text)],
        plain=text,
        source_format=DocFormat.DJVU,
        engine="djvutxt",
    )


__all__ = ["read_txt", "read_txt_model", "read_djvu"]
