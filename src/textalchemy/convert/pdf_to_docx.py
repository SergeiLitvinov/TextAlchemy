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
        prepared = self._prepare(input_path, output_path)
        if prepared is None:
            return ConversionResult(Path(input_path), Path(output_path), False, "Input file not found")
        input_path, output_path = prepared
        try:
            import pdf2docx
            pdf2docx.parse(str(input_path), str(output_path), multi_processing=True)
        except Exception as e:
            return ConversionResult(input_path, output_path, False, str(e))
        return ConversionResult(input_path, output_path, output_path.exists())


class PyMuPdfConverter(BaseConverter):
    """PDF → DOCX через PyMuPDF.

    Стратегия (best-effort для «сложных» PDF):
    * Извлечь текст каждой страницы и положить в DOCX.
    * Если на странице мало текста (< 50 символов) — отрендерить её в PNG
      и вставить как изображение (для сканов и формул).
    """

    @property
    def name(self) -> str:
        return "pymupdf"

    def __init__(self, render_dpi: int = 150, text_threshold: int = 50) -> None:
        self.render_dpi = render_dpi
        self.text_threshold = text_threshold

    def convert(self, input_path: str | Path, output_path: str | Path) -> ConversionResult:
        prepared = self._prepare(input_path, output_path)
        if prepared is None:
            return ConversionResult(Path(input_path), Path(output_path), False, "Input file not found")
        input_path, output_path = prepared
        try:
            import fitz
            from docx import Document as DocxDocument
            from docx.shared import Inches, Pt

            d = DocxDocument()
            with fitz.open(str(input_path)) as doc:
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    text_dict = page.get_text("dict") or {}
                    blocks = text_dict.get("blocks", []) if isinstance(text_dict, dict) else []
                    # Собираем видимый текст; если нет ни одного символа — скан.
                    has_text = False
                    for b in blocks:
                        if b.get("type") != 0:
                            continue
                        for line in b.get("lines", []):
                            for span in line.get("spans", []):
                                if (span.get("text") or "").strip():
                                    has_text = True
                                    break
                            if has_text:
                                break
                        if has_text:
                            break
                    if has_text:
                        # Текстовая страница — текстом, с сохранением размера шрифта.
                        for b in blocks:
                            if b.get("type") != 0:
                                continue
                            for line in b.get("lines", []):
                                spans = line.get("spans", [])
                                line_text = "".join(s.get("text", "") for s in spans).strip()
                                if not line_text:
                                    continue
                                para = d.add_paragraph()
                                for s in spans:
                                    run = para.add_run(s.get("text", ""))
                                    size = s.get("size")
                                    if size:
                                        try:
                                            run.font.size = Pt(float(size))
                                        except Exception:  # noqa: BLE001
                                            pass
                    else:
                        # Реально пустая страница (скан, формулы) — картинкой.
                        pix = page.get_pixmap(dpi=self.render_dpi)
                        img_path = output_path.parent / f".__pymupdf_page_{page_num}.png"
                        pix.save(str(img_path))
                        try:
                            width_in = 6.0
                            ratio = pix.height / max(pix.width, 1)
                            d.add_picture(
                                str(img_path),
                                width=Inches(width_in),
                                height=Inches(width_in * ratio),
                            )
                        finally:
                            img_path.unlink(missing_ok=True)
                    d.add_page_break()
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
            result = subprocess.run(["soffice", "--version"], capture_output=True, text=True)
            if result.returncode == 0:
                return "soffice"
        except FileNotFoundError:
            pass
        return None

    def convert(self, input_path: str | Path, output_path: str | Path) -> ConversionResult:
        prepared = self._prepare(input_path, output_path)
        if prepared is None:
            return ConversionResult(Path(input_path), Path(output_path), False, "Input file not found")
        input_path, output_path = prepared
        if not self.libreoffice_path:
            return ConversionResult(input_path, output_path, False, "LibreOffice not found")
        try:
            temp_odt = output_path.parent / (input_path.stem + ".odt")
            lo_dir = Path(self.libreoffice_path).parent
            env = os.environ.copy()
            env["PATH"] = str(lo_dir) + ";" + env.get("PATH", "")

            try:
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
            finally:
                temp_odt.unlink(missing_ok=True)
        except subprocess.TimeoutExpired:
            return ConversionResult(input_path, output_path, False, "Timeout")
        except Exception as e:
            return ConversionResult(input_path, output_path, False, str(e))
        return ConversionResult(input_path, output_path, output_path.exists())


class FanOutConverter(BaseConverter):
    """Пробует движки по очереди, пока один не выдаст валидный DOCX.

    Цепочка по умолчанию: ``pdf2docx → pymupdf → libreoffice``. Первый успех побеждает.
    Используется, когда конкретный движок неизвестен или нужен best-effort.
    """

    @property
    def name(self) -> str:
        return "fanout"

    def __init__(self, tools: list[str] | None = None) -> None:
        # pdf2docx сохраняет текст и разметку (не растровые вставки),
        # поэтому он — приоритетный. pymupdf (с растровым фолбэком для
        # сканов) оставлен последним.
        self.tools = tools or ["pdf2docx", "libreoffice", "pymupdf"]

    def convert(self, input_path: str | Path, output_path: str | Path) -> ConversionResult:
        prepared = self._prepare(input_path, output_path)
        if prepared is None:
            return ConversionResult(Path(input_path), Path(output_path), False, "Input file not found")
        input_path, output_path = prepared
        last_error = ""
        tried: list[str] = []
        for tool in self.tools:
            try:
                converter = create_converter(tool)
            except ConvertError as e:
                tried.append(f"{tool}:unavailable")
                last_error = str(e)
                continue
            tried.append(tool)
            result = converter.convert(input_path, output_path)
            if result.success and result.output_path.exists() and result.output_path.stat().st_size > 0:
                self._postprocess(output_path)
                return ConversionResult(
                    input_path, result.output_path, True, None,
                )
            last_error = f"{tool}: {result.error}"
        return ConversionResult(
            input_path, Path(output_path), False,
            f"all engines failed (tried: {tried}); last error: {last_error}",
        )

    @staticmethod
    def _postprocess(output_path: str | Path) -> None:
        """Восстановить структуру (заголовки) и нормализовать шрифт."""
        try:
            from textalchemy.convert.docx_postprocess import (
                apply_heading_styles,
                ensure_min_font,
            )

            ensure_min_font(output_path)
            apply_heading_styles(output_path)
        except Exception:  # noqa: BLE001
            # Пост-обработка — best-effort, не ломаем результат конвертации.
            pass


def create_converter(tool: str) -> BaseConverter:
    converters = {
        "pdf2docx": Pdf2DocxConverter,
        "pymupdf": PyMuPdfConverter,
        "libreoffice": LibreOfficeConverter,
        "fanout": FanOutConverter,
    }
    if tool not in converters:
        raise ConvertError(f"Unknown tool: {tool}. Available: {list(converters.keys())}")
    return converters[tool]()
