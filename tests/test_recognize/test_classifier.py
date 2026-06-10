from textalchemy.recognize import DocumentClassifier


def test_classifier_empty():
    clf = DocumentClassifier()
    result = clf.classify("")
    assert result.doc_type == "unknown"
    assert result.confidence == 0.0


def test_classifier_article():
    clf = DocumentClassifier()
    result = clf.classify("This article is published in a journal with DOI")
    assert result.doc_type == "article"
    assert result.confidence > 0


def test_classifier_dissertation():
    clf = DocumentClassifier()
    result = clf.classify("Диссертация на соискание ученой степени кандидата наук")
    assert result.doc_type == "dissertation"


def test_classifier_patent():
    clf = DocumentClassifier()
    result = clf.classify("Патент на изобретение РФ")
    assert result.doc_type == "patent"


def test_classifier_file_no_file():
    clf = DocumentClassifier()
    result = clf.classify_file("nonexistent.txt")
    assert result.confidence == 0.0
