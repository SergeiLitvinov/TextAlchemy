import os
import subprocess
from pathlib import Path

from textalchemy.convert.base import BaseConverter, ConversionResult
from textalchemy.core.exceptions import ConvertError


class Pdf2DocxConverter(BaseConverter):
    @property
    def name(self) -> str:
        return "pdf2docx"

    def convert(self, input_path: str | Path, output_path: str | Path) -> ConversionResult:
        input_path = Path(input_path)
        output_path = Path(output_path)
        if not input_path.exists():
            return ConversionResult(input_path, output_path, False, "Input file not found")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import pdf2docx
            pdf2docx.parse(str(input_path), str(output_path), multi_processing=True)
        except Exception as e:
            return ConversionResult(input_path, output_path, False, str(e))
        return ConversionResult(input_path, output_path, output_path.exists())


class PyMuPdfConverter(BaseConverter):
    @property
    def name(self) -> str:
        return "pymupdf"

    def convert(self, input_path: str | Path, output_path: str | Path) -> ConversionResult:
        input_path = Path(input_path)
        output_path = Path(output_path)
        if not input_path.exists():
            return ConversionResult(input_path, output_path, False, "Input file not found")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import fitz
            from docx import Document as DocxDocument
            doc = fitz.open(str(input_path))
            d = DocxDocument()
            for page_num in range(len(doc)):
                page = doc[page_num]
                d.add_paragraph(page.get_text())
            d.save(str(output_path))
        except Exception as e:
            return ConversionResult(input_path, output_path, False, str(e))
        return ConversionResult(input_path, output_path, output_path.exists())


class LibreOfficeConverter(BaseConverter):
    @property
    def name(self) -> str:
        return "libreoffice"

    def __init__(self, libreoffice_path: str | None = None):
        self.libreoffice_path = libreoffice_path or self._find_libreoffice_path()

    def _find_libreoffice_path(self) -> str | None:
        possible = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        for path in possible:
            if os.path.exists(path):
                return path
        try:
            result = subprocess.run(["soffice", "--version"], capture_output=True, text=True, shell=True)
            if result.returncode == 0:
                return "soffice"
        except FileNotFoundError:
            pass
        return None

    def convert(self, input_path: str | Path, output_path: str | Path) -> ConversionResult:
        input_path = Path(input_path)
        output_path = Path(output_path)
        if not input_path.exists():
            return ConversionResult(input_path, output_path, False, "Input file not found")
        if not self.libreoffice_path:
            return ConversionResult(input_path, output_path, False, "LibreOffice not found")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            temp_odt = output_path.parent / (input_path.stem + ".odt")
            lo_dir = Path(self.libreoffice_path).parent
            env = os.environ.copy()
            env["PATH"] = str(lo_dir) + ";" + env.get("PATH", "")

            cmd1 = [self.libreoffice_path, "--headless", "--writer",
                    "--convert-to", "odt", "--outdir", str(output_path.parent.absolute()),
                    str(input_path.absolute())]
            r1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=300, env=env)
            if not temp_odt.exists():
                return ConversionResult(input_path, output_path, False, r1.stderr[:200])

            cmd2 = [self.libreoffice_path, "--headless",
                    "--convert-to", "docx:MS Word 2007 XML",
                    "--outdir", str(output_path.parent.absolute()),
                    str(temp_odt.absolute())]
            subprocess.run(cmd2, capture_output=True, text=True, timeout=300, env=env)
            if temp_odt.exists():
                temp_odt.unlink()
        except subprocess.TimeoutExpired:
            return ConversionResult(input_path, output_path, False, "Timeout")
        except Exception as e:
            return ConversionResult(input_path, output_path, False, str(e))
        return ConversionResult(input_path, output_path, output_path.exists())


def create_converter(tool: str) -> BaseConverter:
    converters = {
        "pdf2docx": Pdf2DocxConverter,
        "pymupdf": PyMuPdfConverter,
        "libreoffice": LibreOfficeConverter,
    }
    if tool not in converters:
        raise ConvertError(f"Unknown tool: {tool}. Available: {list(converters.keys())}")
    return converters[tool]()
