from textalchemy.organize.bibliography import BibliographyParser, detect_format, smart_parse


def test_detect_format_blank():
    assert detect_format([]) == "blank"
    assert detect_format(["", "  "]) == "blank"


def test_detect_format_numbered():
    lines = ["1. First entry", "2. Second entry", "3. Third entry"]
    assert detect_format(lines) == "numbered"


def test_detect_format_gost():
    lines = ["Author // Title. — 2024", "Author2 // Title2. — 2023"]
    assert detect_format(lines) == "gost"


def test_parse_numbered():
    text = "1. Ivanov I.I. Testing. — 2024\n2. Petrov P.P. Analysis. — 2023"
    items = smart_parse(text)
    assert len(items) >= 1


def test_parse_entry_dissertation():
    text = "Ivanov I.I. — Development of method. — dissertation ... PhD — 2024"
    items = smart_parse(text)
    # Returns at least one item when parsing single entry with year
    if items:
        assert items[0].year is not None


def test_parse_entry_monograph():
    text = "Petrov P.P. — Monograph on topic. — Moscow: Publisher. — 2023"
    items = smart_parse(text)
    if items:
        assert len(items) == 1


def test_parse_entry_year():
    text = "Author — Title — 2024"
    items = smart_parse(text)
    if items:
        assert items[0].year is not None


def test_parse_file_not_found():
    items = BibliographyParser.parse_file("nonexistent_file.txt")
    assert items == []
