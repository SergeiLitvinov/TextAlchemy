import hashlib
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from textalchemy.convert.base import BaseConverter, ConversionResult
from textalchemy.core.exceptions import ConvertError

_CACHE_DIR = Path.home() / ".cache" / "textalchemy" / "convert"


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _cache_key(path: Path, engine: str) -> Path:
    return _CACHE_DIR / f"{_file_hash(path)}_{engine}.docx"


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

    def __init__(self, render_dpi: int = 150, text_threshold: int = 50) -> None:
        self.render_dpi = render_dpi
        self.text_threshold = text_threshold

    def convert(self, input_path: str | Path, output_path: str | Path) -> ConversionResult:
        input_path = Path(input_path)
        output_path = Path(output_path)
        if not input_path.exists():
            return ConversionResult(input_path, output_path, False, "Input file not found")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import fitz
            from docx import Document as DocxDocument
            from docx.shared import Inches

            pdf = fitz.open(str(input_path))
            d = DocxDocument()

            for page_num in range(len(pdf)):
                page = pdf[page_num]
                text = (page.get_text() or "").strip()

                if len(text) >= self.text_threshold:
                    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", [])
                    self._add_text_blocks(d, blocks)
                else:
                    pix = page.get_pixmap(dpi=self.render_dpi)
                    import io

                    d.add_picture(io.BytesIO(pix.tobytes("png")), width=Inches(6.0))

                d.add_page_break()

            d.save(str(output_path))
        except Exception as e:
            return ConversionResult(input_path, output_path, False, str(e))
        return ConversionResult(input_path, output_path, output_path.exists())

    @staticmethod
    def _add_text_blocks(d, blocks):
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt

        para_buffer = []
        para_font_size = None
        para_align = WD_ALIGN_PARAGRAPH.LEFT

        def flush():
            nonlocal para_buffer, para_font_size, para_align
            if not para_buffer:
                return
            text = "".join(para_buffer).strip()
            if not text:
                return
            p = d.add_paragraph()
            p.alignment = para_align
            run = p.add_run(text)
            if para_font_size and para_font_size >= 14:
                level = 1 if para_font_size >= 16 else 2
                p.style = d.styles[f"Heading {level}"]
            elif para_font_size:
                run.font.size = Pt(para_font_size)
            para_buffer = []
            para_font_size = None
            para_align = WD_ALIGN_PARAGRAPH.LEFT

        for block in blocks:
            if block.get("type") != 0:
                continue

            lines = block.get("lines", [])
            if not lines:
                continue

            block_align_val = block.get("number", 0)
            align_map = {0: WD_ALIGN_PARAGRAPH.LEFT, 1: WD_ALIGN_PARAGRAPH.CENTER, 2: WD_ALIGN_PARAGRAPH.RIGHT}
            block_align = align_map.get(block_align_val, WD_ALIGN_PARAGRAPH.LEFT)

            for line in lines:
                spans = line.get("spans", [])
                if not spans:
                    continue

                line_text = ""
                line_font_size = max(s.get("size", 12) for s in spans)

                for span in spans:
                    line_text += span.get("text", "")

                is_para_end = line_text.rstrip()[-1:] in (".", "!", "?", ":", ";")

                if para_font_size is not None and abs(line_font_size - para_font_size) > 2:
                    flush()

                para_buffer.append(line_text)
                para_font_size = line_font_size
                para_align = block_align

                if is_para_end:
                    flush()

        flush()


class LibreOfficeConverter(BaseConverter):
    @property
    def name(self) -> str:
        return "libreoffice"

    def __init__(self, libreoffice_path: str | None = None):
        self.libreoffice_path = libreoffice_path or self._find_libreoffice_path()

    @staticmethod
    def _find_libreoffice_path() -> str | None:
        possible = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            r"/usr/lib/libreoffice/program/soffice",
            r"/usr/local/libreoffice/program/soffice",
            r"/Applications/LibreOffice.app/Contents/MacOS/soffice",
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

        import shutil

        soffice = shutil.which("soffice")
        if soffice:
            return soffice
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
            path_key = str("PATH")
            env[path_key] = str(lo_dir) + str(os.pathsep) + env.get(path_key, "")

            cmd1 = [
                self.libreoffice_path,
                "--headless",
                "--writer",
                "--infilter",
                "pdf:writer_pdf_import",
                "--convert-to",
                "odt",
                "--outdir",
                str(output_path.parent.absolute()),
                str(input_path.absolute()),
            ]
            r1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=300, env=env)
            if not temp_odt.exists():
                return ConversionResult(input_path, output_path, False, r1.stderr[:200])

            cmd2 = [
                self.libreoffice_path,
                "--headless",
                "--convert-to",
                "docx:MS Word 2007 XML",
                "--outdir",
                str(output_path.parent.absolute()),
                str(temp_odt.absolute()),
            ]
            subprocess.run(cmd2, capture_output=True, text=True, timeout=300, env=env)
            if temp_odt.exists():
                temp_odt.unlink()
        except subprocess.TimeoutExpired:
            return ConversionResult(input_path, output_path, False, "Timeout")
        except Exception as e:
            return ConversionResult(input_path, output_path, False, str(e))
        return ConversionResult(input_path, output_path, output_path.exists())


class FanOutConverter(BaseConverter):
    """Пробует движки параллельно и выбирает лучший результат.

    Цепочка по умолчанию: ``pdf2docx → pymupdf → libreoffice``.
    Движки запускаются параллельно через ThreadPoolExecutor.
    Каждый движок пишет во временный файл; лучший копируется в output_path.

    Результаты кешируются по SHA-256 хешу входного файла.
    """

    @property
    def name(self) -> str:
        return "fanout"

    def __init__(self, tools: list[str] | None = None, timeout: int = 300, use_cache: bool = True) -> None:
        self.tools = tools or ["pdf2docx", "pymupdf", "libreoffice"]
        self.timeout = timeout
        self.use_cache = use_cache

    def convert(self, input_path: str | Path, output_path: str | Path) -> ConversionResult:
        input_path = Path(input_path)
        output_path = Path(output_path)
        if not input_path.exists():
            return ConversionResult(input_path, output_path, False, "Input file not found")

        if self.use_cache:
            for tool in self.tools:
                cached = _cache_key(input_path, tool)
                if cached.exists() and cached.stat().st_size > 0:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(cached), str(output_path))
                    return ConversionResult(input_path, output_path, True, None)

        results: dict[str, ConversionResult] = {}
        errors: list[str] = []
        temp_dir = Path(tempfile.mkdtemp(prefix="fanout_"))

        try:
            with ThreadPoolExecutor(max_workers=len(self.tools)) as executor:
                future_map = {}
                for tool in self.tools:
                    try:
                        converter = create_converter(tool)
                        temp_out = temp_dir / f"{tool}_{output_path.name}"
                        future = executor.submit(converter.convert, input_path, temp_out)
                        future_map[future] = tool
                    except ConvertError as e:
                        errors.append(f"{tool}:unavailable ({e})")

                for future in as_completed(future_map, timeout=self.timeout):
                    tool = future_map[future]
                    try:
                        result = future.result()
                        results[tool] = result
                    except Exception as e:
                        errors.append(f"{tool}:{e}")

            successful = [
                (tool, r)
                for tool, r in results.items()
                if r.success and r.output_path.exists() and r.output_path.stat().st_size > 0
            ]

            if not successful:
                last_error = errors[-1] if errors else "all engines failed"
                return ConversionResult(input_path, output_path, False, last_error)

            successful.sort(key=lambda x: x[1].output_path.stat().st_size, reverse=True)
            best_result = successful[0][1]

            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(best_result.output_path), str(output_path))

            if self.use_cache:
                _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_dst = _cache_key(input_path, successful[0][0])
                shutil.copy2(str(output_path), str(cache_dst))

            return ConversionResult(input_path, output_path, True, None)

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


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
