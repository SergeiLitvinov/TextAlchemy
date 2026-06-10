from textalchemy.organize.bibliography import (
    BibItem,
    BibliographyParser,
    _extract_authors,
    _extract_doc_type,
    _extract_title,
    detect_format,
    smart_parse,
)


def test_extract_authors_simple():
    authors = _extract_authors("Ivanov I.I. Title of work")
    assert len(authors) > 0


def test_extract_authors_multiple():
    authors = _extract_authors("Ivanov I.I., Petrov P.P. Title")
    assert len(authors) >= 1


def test_extract_authors_empty():
    authors = _extract_authors("No author here")
    assert authors == []


def test_extract_title_simple():
    title = _extract_title("Ivanov I.I. Research on something")
    assert title is not None


def test_extract_title_empty():
    title = _extract_title("")
    assert title is None or title == ""


def test_extract_doc_type_dissertation():
    dt = _extract_doc_type("диссертация ... канд. наук")
    assert dt == "dissertation"


def test_extract_doc_type_patent():
    dt = _extract_doc_type("патент на изобретение")
    assert dt == "patent"


def test_extract_doc_type_standard():
    dt = _extract_doc_type("гост Р 12345-2023")
    assert dt == "standard"


def test_extract_doc_type_empty():
    dt = _extract_doc_type("")
    assert dt == "unknown"


def test_detect_format_empty():
    assert detect_format("") == "blank"


def test_detect_format_single():
    assert detect_format("Just one line") == "simple_lines"


def test_smart_parse_empty():
    items = smart_parse("")
    assert items == []


def test_smart_parse_garbage():
    items = smart_parse("!@#$%^&*()")
    assert isinstance(items, list)


def test_parse_item():
    item = BibliographyParser.parse_item(1, "Ivanov I.I. Title")
    assert item.index == 1


def test_to_json_empty():
    assert BibliographyParser.to_json([]) == []


def test_to_markdown_empty():
    md = BibliographyParser.to_markdown([])
    assert md == ""


def test_to_gost_empty():
    gost = BibliographyParser.to_gost([])
    assert gost == ""


def test_bibitem_defaults():
    item = BibItem()
    assert item.index == 0
    assert item.authors == []
    assert item.title == ""
    assert item.year is None
    assert item.doc_type == "unknown"
