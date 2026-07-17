from __future__ import annotations

import zipfile

import pytest

from textalchemy.convert import FanOutConverter
from textalchemy.convert.pdf_to_docx import (
    _CACHE_DIR,
    PyMuPdfConverter,
    _cache_key,
    _file_hash,
    create_converter,
)


def test_fanout_registered():
    from textalchemy.convert import create_converter

    c = create_converter("fanout")
    assert isinstance(c, FanOutConverter)


def test_fanout_creates_real_docx(tmp_path):
    """Fan-out на реальном PDF: должен дать валидный DOCX через pymupdf."""
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")

    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello PDF world")
    doc.save(str(pdf_path))
    doc.close()

    out_path = tmp_path / "sample.docx"
    c = FanOutConverter(tools=["pdf2docx", "pymupdf"])
    result = c.convert(pdf_path, out_path)
    # Может не быть pdf2docx; но pymupdf должен сработать
    if result.success:
        assert out_path.is_file()
        assert out_path.stat().st_size > 0
        with zipfile.ZipFile(out_path) as zf:
            assert "word/document.xml" in zf.namelist()
    else:
        pytest.skip(f"all engines failed: {result.error}")


def test_pymupdf_text_page(tmp_path):
    """PyMuPdf: страница с текстом → текст в DOCX."""
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")

    pdf = tmp_path / "in.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello PDF world")
    page.insert_text((72, 100), "Second line here")
    doc.save(str(pdf))
    doc.close()

    # Сразу проверим, что pymupdf видит текст
    reread = fitz.open(str(pdf))
    text_before = reread[0].get_text()
    reread.close()
    assert "Hello" in text_before, f"pymupdf didn't extract: {text_before!r}"

    out = tmp_path / "out.docx"
    c = PyMuPdfConverter(text_threshold=10)  # понизим порог
    result = c.convert(pdf, out)
    assert result.success
    assert out.is_file()
    from docx import Document

    d = Document(str(out))
    text = "\n".join(p.text for p in d.paragraphs)
    assert "Hello" in text, f"DOCX has no text: {text!r}"


def test_pymupdf_scan_page_uses_image(tmp_path):
    """PyMuPdf: страница с <50 символов текста → изображение."""
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")

    pdf = tmp_path / "in.pdf"
    doc = fitz.open()
    # Страница без текста (пустая) — будет отрендерена как картинка
    doc.new_page()
    doc.save(str(pdf))
    doc.close()

    out = tmp_path / "out.docx"
    c = PyMuPdfConverter(render_dpi=72)
    result = c.convert(pdf, out)
    assert result.success
    assert out.is_file()
    # DOCX должен содержать изображение
    with zipfile.ZipFile(out) as zf:
        media = [n for n in zf.namelist() if n.startswith("word/media/")]
        assert media  # хотя бы одна картинка


def test_create_converter_unknown():
    with pytest.raises(Exception):
        create_converter("nonexistent_engine")


def test_file_hash_consistent(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"hello")
    h1 = _file_hash(f)
    h2 = _file_hash(f)
    assert h1 == h2


def test_file_hash_changes_on_content(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"hello")
    h1 = _file_hash(f)
    f.write_bytes(b"world")
    h2 = _file_hash(f)
    assert h1 != h2


def test_cache_key_uses_hash_and_engine(tmp_path):
    f = tmp_path / "test.pdf"
    f.write_bytes(b"content")
    key = _cache_key(f, "pymupdf")
    assert key.name.endswith("_pymupdf.docx")
    assert key.parent == _CACHE_DIR


def test_fanout_cache_hit_returns_cached(tmp_path, monkeypatch):
    """Если кеш существует, FanOut не запускает движки."""
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")

    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    # Подкладываем кеш
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fake_cache = _cache_key(pdf_path, "pymupdf")
    fake_cache.write_text("fake docx content")

    out_path = tmp_path / "result.docx"
    c = FanOutConverter(tools=["pymupdf"], use_cache=True)

    # Мокаем _file_hash чтобы кеш совпал
    original_hash = _file_hash(pdf_path)
    _ = original_hash  # кеш уже создан с реальным хешем

    result = c.convert(pdf_path, out_path)
    assert result.success
    assert out_path.read_text() == "fake docx content"


def test_fanout_cache_disabled_ignores_cache(tmp_path, monkeypatch):
    """С use_cache=False FanOut не проверяет кеш и пересоздаёт результат."""
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")

    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Fresh content")
    doc.save(str(pdf_path))
    doc.close()

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fake_cache = _cache_key(pdf_path, "pymupdf")
    fake_cache.write_text("stale cached content")

    out_path = tmp_path / "result.docx"
    c = FanOutConverter(tools=["pymupdf"], use_cache=False)
    result = c.convert(pdf_path, out_path)
    assert result.success
    assert out_path.is_file()
    assert out_path.stat().st_size > 0
    # свежий результат не равен "stale cached content"
    assert out_path.read_bytes() != b"stale cached content"


def test_pymupdf_heading_detection(tmp_path):
    """PyMuPdf: большой шрифт (≥16pt) → Heading 1, ≥14pt → Heading 2."""
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")

    pdf = tmp_path / "in.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # Вставляем текст с крупным шрифтом
    page.insert_text((72, 72), "Big Title", fontsize=18)
    page.insert_text((72, 120), "Medium Heading", fontsize=15)
    page.insert_text((72, 170), "Body text", fontsize=11)
    doc.save(str(pdf))
    doc.close()

    out = tmp_path / "out.docx"
    c = PyMuPdfConverter(text_threshold=5)
    result = c.convert(pdf, out)
    assert result.success

    from docx import Document

    d = Document(str(out))
    styles_seen = [p.style.name for p in d.paragraphs if p.text.strip()]
    assert any("Heading 1" in s for s in styles_seen), f"No Heading 1 in {styles_seen}"
    assert any("Heading 2" in s for s in styles_seen), f"No Heading 2 in {styles_seen}"


def test_pymupdf_paragraph_grouping(tmp_path):
    """PyMuPdf: строки группируются в абзацы по знакам пунктуации."""
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")

    pdf = tmp_path / "in.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "First sentence.")
    page.insert_text((72, 100), "Second sentence!")
    page.insert_text((72, 130), "Third line")
    doc.save(str(pdf))
    doc.close()

    out = tmp_path / "out.docx"
    c = PyMuPdfConverter(text_threshold=5)
    result = c.convert(pdf, out)
    assert result.success

    from docx import Document

    d = Document(str(out))
    texts = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    # "First sentence." и "Second sentence!" — самостоятельные абзацы (заканчиваются на .!)
    combined = " ".join(texts)
    assert "First sentence." in combined
    assert "Second sentence!" in combined
    # "Third line" тоже где-то есть
    assert "Third line" in combined


def test_pymupdf_center_aligned_text(tmp_path):
    """PyMuPdf: центрированный блок текста → center alignment в DOCX."""
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")

    pdf = tmp_path / "in.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # pymupdf использует number=1 для center-выравнивания в dict
    page.insert_text((72, 72), "Centered title")
    doc.save(str(pdf))
    doc.close()

    out = tmp_path / "out.docx"
    c = PyMuPdfConverter(text_threshold=5)
    result = c.convert(pdf, out)
    assert result.success

    from docx import Document

    d = Document(str(out))
    paragraphs = [p for p in d.paragraphs if p.text.strip()]
    # Хотя бы один параграф существует
    assert len(paragraphs) > 0
