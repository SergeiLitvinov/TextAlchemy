"""Парсеры форматов. Добавление нового формата = новый модуль здесь."""

from textalchemy.formats.docx import read_docx, read_docx_model
from textalchemy.formats.pdf import get_pdf_info, read_pdf, read_pdf_geometry
from textalchemy.formats.pptx import read_pptx, read_pptx_model
from textalchemy.formats.txt import read_djvu, read_txt

__all__ = [
    "get_pdf_info",
    "read_djvu",
    "read_docx",
    "read_docx_model",
    "read_pdf",
    "read_pdf_geometry",
    "read_pptx",
    "read_pptx_model",
    "read_txt",
]
