"""Тесты extract/emails.py (извлечение email-адресов)."""

from textalchemy.extract.emails import (
    emails_to_docx,
    emails_to_text,
    extract_emails_from_text,
    save_debug_text,
)


class TestExtractEmailsFromText:
    def test_simple_email(self):
        assert extract_emails_from_text("user@example.com") == ["user@example.com"]

    def test_multiple_emails(self):
        text = "a@b.com and c@d.org and e@f.net"
        result = extract_emails_from_text(text)
        assert len(result) == 3
        assert "a@b.com" in result
        assert "c@d.org" in result
        assert "e@f.net" in result

    def test_duplicates_removed(self):
        result = extract_emails_from_text("a@b.com and a@b.com")
        assert result == ["a@b.com"]

    def test_invalid_tld_filtered(self):
        text = "real@example.com fake@example.test"
        result = extract_emails_from_text(text)
        assert result == ["real@example.com"]

    def test_no_email(self):
        assert extract_emails_from_text("no email here") == []

    def test_empty_text(self):
        assert extract_emails_from_text("") == []

    def test_email_in_mixed_text(self):
        text = "Contact us at support@company.com for help."
        assert extract_emails_from_text(text) == ["support@company.com"]

    def test_email_with_dots(self):
        assert extract_emails_from_text("first.last@domain.co.uk") == ["first.last@domain.co.uk"]

    def test_email_with_plus(self):
        assert extract_emails_from_text("tag+filter@domain.com") == ["tag+filter@domain.com"]

    def test_sorted_output(self):
        result = extract_emails_from_text("c@x.com a@x.com b@x.com")
        assert len(result) == 3
        assert "a@x.com" in result
        assert "b@x.com" in result
        assert "c@x.com" in result

    def test_case_insensitive_dedup(self):
        result = extract_emails_from_text("User@Example.com user@example.com")
        assert len(result) == 2


class TestEmailsToDocx:
    def test_creates_docx(self, tmp_path):
        out = tmp_path / "result.docx"
        result = emails_to_docx(["a@b.com", "c@d.com"], "test.pdf", out)
        assert result == out
        assert out.exists()
        assert out.suffix == ".docx"

    def test_empty_list(self, tmp_path):
        out = tmp_path / "empty.docx"
        result = emails_to_docx([], "test.pdf", out)
        assert result == out
        assert out.exists()

    def test_creates_parent_dir(self, tmp_path):
        out = tmp_path / "sub" / "result.docx"
        result = emails_to_docx(["a@b.com"], "test.pdf", out)
        assert result == out
        assert out.exists()


class TestEmailsToText:
    def test_creates_txt(self, tmp_path):
        out = tmp_path / "result.txt"
        result = emails_to_text(["a@b.com", "c@d.com"], "test.pdf", out)
        assert result == out
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "a@b.com" in content
        assert "c@d.com" in content

    def test_empty_list(self, tmp_path):
        out = tmp_path / "empty.txt"
        result = emails_to_text([], "test.pdf", out)
        assert result == out
        assert "не найдены" in out.read_text(encoding="utf-8")

    def test_sorted_output(self, tmp_path):
        out = tmp_path / "sorted.txt"
        emails_to_text(["z@x.com", "a@x.com"], "test.pdf", out)
        content = out.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        assert lines == ["a@x.com", "z@x.com"]


class TestSaveDebugText:
    def test_creates_debug_file(self, tmp_path):
        out = tmp_path / "debug.txt"
        result = save_debug_text("Some text", "test.pdf", 10, 5, 5, out)
        assert result == out
        content = out.read_text(encoding="utf-8")
        assert "test.pdf" in content
        assert "Some text" in content
        assert "10" in content
        assert "5" in content

    def test_empty_text(self, tmp_path):
        out = tmp_path / "debug.txt"
        save_debug_text("", "empty.pdf", 0, 0, 0, out)
        assert out.exists()
