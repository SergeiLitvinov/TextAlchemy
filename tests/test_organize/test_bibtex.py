from textalchemy.organize.bibtex import extract_year, generate_bib, make_bibtex_entry, sanitize_key


def test_sanitize_key():
    key = sanitize_key("test file name.pdf")
    assert all(c.isalnum() for c in key)


def test_sanitize_key_empty():
    key = sanitize_key("!@#$%")
    assert key == "ref"


def test_extract_year_found():
    assert extract_year("Published in 2024") == "2024"


def test_extract_year_not_found():
    assert extract_year("No year here") == "n.d."


def test_make_bibtex_entry():
    entry = make_bibtex_entry("test.pdf", {"title": "Test Title", "author": "Author A"})
    assert "@misc{" in entry
    assert "Test Title" in entry
    assert "Author A" in entry


def test_make_bibtex_entry_empty():
    entry = make_bibtex_entry("test.pdf", {})
    assert "@misc{" in entry


def test_generate_bib_no_folder(tmp_path):
    try:
        generate_bib(tmp_path / "nonexistent")
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_generate_bib_empty_folder(tmp_path):
    bib = generate_bib(tmp_path)
    assert bib == ""
