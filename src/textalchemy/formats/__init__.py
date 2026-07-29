"""Парсеры форматов. Добавление нового формата = новый модуль здесь."""

from textalchemy.formats.docx import read_docx, read_docx_model
from textalchemy.formats.pdf import get_pdf_info, read_pdf
from textalchemy.formats.txt import read_djvu, read_txt

__all__ = ["read_docx", "read_docx_model", "read_pdf", "get_pdf_info", "read_txt", "read_djvu"]
