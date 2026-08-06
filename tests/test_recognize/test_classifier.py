"""Тесты классификатора типов документов по ключевым словам."""
from __future__ import annotations

import pytest

from textalchemy.recognize import DocumentClassifier
from textalchemy.recognize.classifier import ClassificationResult


def test_classifier_empty():
    clf = DocumentClassifier()
    result = clf.classify("")
    assert result.doc_type == "unknown"
    assert result.confidence == 0.0


def test_classifier_whitespace():
    clf = DocumentClassifier()
    result = clf.classify("   \n\t  ")
    assert result.doc_type == "unknown"


def test_classifier_model_path_unsupported():
    with pytest.raises(NotImplementedError):
        DocumentClassifier(model_path="model.bin")


def test_classifier_article():
    clf = DocumentClassifier()
    result = clf.classify("This article is published in a journal with DOI")
    assert result.doc_type == "article"
    assert result.confidence > 0


def test_classifier_dissertation():
    clf = DocumentClassifier()
    result = clf.classify("диссертация на соискание учёной степени кандидата наук")
    assert result.doc_type == "dissertation"


def test_classifier_patent():
    clf = DocumentClassifier()
    result = clf.classify("патент на изобретение РФ")
    assert result.doc_type == "patent"


def test_classifier_no_keyword_match():
    clf = DocumentClassifier()
    result = clf.classify("qwerty uiоп asdfgh")
    assert result.doc_type == "unknown"
    assert result.confidence == 0.0
    assert set(result.scores) == set(clf.DOC_TYPES)


def test_classifier_returns_classification_result():
    clf = DocumentClassifier()
    result = clf.classify("монография")
    assert isinstance(result, ClassificationResult)
    assert result.doc_type == "monograph"


def test_classifier_file_no_file():
    clf = DocumentClassifier()
    result = clf.classify_file("nonexistent.txt")
    assert result.confidence == 0.0


def test_classifier_file_utf8(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("This research paper has a DOI 10.1000/xyz", encoding="utf-8")
    clf = DocumentClassifier()
    assert clf.classify_file(path).doc_type == "article"


def test_classifier_file_cp1251_fallback(tmp_path):
    path = tmp_path / "doc.txt"
    # Последовательность, невалидная в UTF-8, но валидная в cp1251.
    path.write_bytes("статья в журнале".encode("cp1251"))
    clf = DocumentClassifier()
    assert clf.classify_file(path).doc_type == "article"


def test_classifier_file_binary_oserror(tmp_path, monkeypatch):
    path = tmp_path / "doc.txt"
    path.write_bytes(b"\x00\x01\x02\xff\xfe")
    clf = DocumentClassifier()

    def boom(*args, **kwargs):
        raise OSError("unreadable")

    monkeypatch.setattr("textalchemy.recognize.classifier.Path.read_text", boom)
    assert clf.classify_file(path).confidence == 0.0
