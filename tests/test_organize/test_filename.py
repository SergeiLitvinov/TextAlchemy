from textalchemy.organize.filename import DocType, abbreviate_title, build_filename, format_authors


def test_doc_type_from_str():
    assert DocType.from_str("article") == DocType.ARTICLE
    assert DocType.from_str("dissertation") == DocType.DISSERTATION
    assert DocType.from_str("unknown") == DocType.UNKNOWN


def test_doc_type_short_rus():
    assert DocType.ARTICLE.short_rus() == "статья"
    assert DocType.DISSERTATION.short_rus() == "дисс"
    assert DocType.BOOK.short_rus() == "книга"


def test_abbreviate_title_short():
    title = "Short title"
    result = abbreviate_title(title, max_len=50)
    assert result == "short_title" or result == title


def test_abbreviate_title_long():
    title = "This is a very long title for testing the abbreviate function"
    result = abbreviate_title(title, max_len=30)
    assert len(result) <= 33


def test_format_authors_single():
    result = format_authors(["Ivanov I.I."])
    assert len(result) > 0


def test_format_authors_multiple():
    result = format_authors(["Ivanov I.I.", "Petrov P.P."])
    assert len(result) > 0
    assert result.count("_") >= 1


def test_format_authors_many():
    result = format_authors(["Ivanov I.I.", "Petrov P.P.", "Sidorov S.S.", "Kuznetsov K.K."])
    assert "et_al" in result or "i_dr" in result or "и_др" in result


def test_build_filename():
    name = build_filename(
        1,
        ["Ivanov I.I."],
        "Test article",
        DocType.ARTICLE,
    )
    assert "01" in name
    assert "article" in name or "статья" in name


def test_build_filename_with_ext():
    name = build_filename(
        1,
        ["Ivanov I."],
        "Test article",
        DocType.ARTICLE,
        ext=".pdf",
    )
    assert name.endswith(".pdf")


def test_build_filename_transliterate():
    name = build_filename(
        1,
        ["Ivanov I.I."],
        "Test article",
        DocType.ARTICLE,
        transliterate_title=True,
    )
    assert name.endswith(".pdf")
