from __future__ import annotations

from pathlib import Path

from textalchemy.core.registry import all_operations
from textalchemy.core.types import Document


def _make_doc(tmp_path: Path, text: str) -> Document:
    p = tmp_path / "test.txt"
    p.write_text(text, encoding="utf-8")
    return Document.from_path(p)


class TestExtractEmails:
    def test_registered(self):
        ids = {s.id for s in all_operations()}
        assert "extract.emails" in ids

    def test_extract_from_txt(self, tmp_path):
        from textalchemy.pipeline.emails_op import extract_emails

        doc = _make_doc(tmp_path, "hello@example.com test@test.com")
        result = extract_emails(doc=doc, use_ocr=False)
        assert "hello@example.com" in result
        assert len(result) == 2

    def test_extract_empty(self, tmp_path):
        from textalchemy.pipeline.emails_op import extract_emails

        doc = _make_doc(tmp_path, "no emails here")
        result = extract_emails(doc=doc, use_ocr=False)
        assert result == []

    def test_extract_multiple(self, tmp_path):
        from textalchemy.pipeline.emails_op import extract_emails

        doc = _make_doc(tmp_path, "a@b.com c@d.org, a@b.com")
        result = extract_emails(doc=doc, use_ocr=False)
        assert result == ["a@b.com", "c@d.org"]


class TestRenderEmailsDocx:
    def test_registered(self):
        ids = {s.id for s in all_operations()}
        assert "render.emails.docx" in ids

    def test_writes_file(self, tmp_path):
        from textalchemy.pipeline.emails_op import render_emails_docx

        out = tmp_path / "result.docx"
        path = render_emails_docx(emails=["a@b.com", "c@d.org"], output_path=out)
        assert path == out
        assert out.is_file()

    def test_empty_list(self, tmp_path):
        from textalchemy.pipeline.emails_op import render_emails_docx

        out = tmp_path / "empty.docx"
        path = render_emails_docx(emails=[], output_path=out)
        assert path == out
        assert out.is_file()


class TestRenderEmailsTxt:
    def test_registered(self):
        ids = {s.id for s in all_operations()}
        assert "render.emails.txt" in ids

    def test_writes_file(self, tmp_path):
        from textalchemy.pipeline.emails_op import render_emails_txt

        out = tmp_path / "result.txt"
        path = render_emails_txt(emails=["a@b.com", "c@d.org"], output_path=out)
        assert path == out
        assert out.is_file()
        content = out.read_text(encoding="utf-8")
        assert "a@b.com" in content
        assert "c@d.org" in content

    def test_empty_list(self, tmp_path):
        from textalchemy.pipeline.emails_op import render_emails_txt

        out = tmp_path / "empty.txt"
        path = render_emails_txt(emails=[], output_path=out)
        assert path == out
        assert out.is_file()
        content = out.read_text(encoding="utf-8")
        assert "не найдены" in content


class TestRenderEmailsDebug:
    def test_registered(self):
        ids = {s.id for s in all_operations()}
        assert "render.emails.debug" in ids

    def test_writes_file(self, tmp_path):
        from textalchemy.pipeline.emails_op import render_emails_debug

        out = tmp_path / "debug.txt"
        path = render_emails_debug(
            full_text="some text",
            output_path=out,
            pdf_name="test.pdf",
            total_pages=5,
            text_pages=3,
            ocr_pages=2,
        )
        assert path == out
        assert out.is_file()
        content = out.read_text(encoding="utf-8")
        assert "some text" in content
        assert "test.pdf" in content
        assert "5" in content
