import json
from pathlib import Path

import pytest

from textalchemy.organize.bibliography import BibItem
from textalchemy.organize.matching import (
    extract_keywords_from_content,
    extract_text_from_file,
    fuzzy_match_author,
    load_manual_matches,
    match_file_to_bibliography,
)


# ── load_manual_matches ────────────────────────────

def test_load_manual_matches_defaults():
    matches = load_manual_matches()
    assert isinstance(matches, dict)
    assert "42. dbbe20b" in matches


def test_load_manual_matches_with_valid_config(tmp_path):
    config = tmp_path / "matches.json"
    config.write_text(json.dumps({"myfile": 5}), encoding="utf-8")
    matches = load_manual_matches(config)
    assert matches["myfile"] == 5
    assert "42. dbbe20b" in matches


def test_load_manual_matches_with_invalid_config(tmp_path):
    config = tmp_path / "bad.json"
    config.write_text("not json", encoding="utf-8")
    matches = load_manual_matches(config)
    assert "42. dbbe20b" in matches


def test_load_manual_matches_nonexistent_config():
    matches = load_manual_matches("nonexistent.json")
    assert isinstance(matches, dict)
    assert "42. dbbe20b" in matches


# ── fuzzy_match_author ─────────────────────────────

def test_fuzzy_match_author_empty():
    assert fuzzy_match_author("", "some content") is False


def test_fuzzy_match_author_whitespace():
    assert fuzzy_match_author("   ", "text") is False


def test_fuzzy_match_author_exact():
    assert fuzzy_match_author("Ivanov", "This is about Ivanov research paper") is True


def test_fuzzy_match_author_case_insensitive():
    assert fuzzy_match_author("ivanov", "About IVANOV paper") is True


def test_fuzzy_match_author_no_match():
    assert fuzzy_match_author("Petrov", "completely unrelated text") is False


def test_fuzzy_match_author_fuzzy_match():
    assert fuzzy_match_author("transformer", "transformers in electrical networks", threshold=0.6) is True


def test_fuzzy_match_author_short_word():
    assert fuzzy_match_author("abc", "some abc text") is True  # short word


# ── extract_keywords_from_content ──────────────────

def test_keywords_overlap():
    ck = extract_keywords_from_content("analysis of power systems and electrical networks")
    tk = extract_keywords_from_content("Analysis of Power Systems")
    assert len(ck & tk) > 0


def test_keywords_no_overlap():
    ck = extract_keywords_from_content("unrelated content")
    tk = extract_keywords_from_content("Computer Science")
    assert len(ck & tk) == 0


def test_keywords_empty():
    assert extract_keywords_from_content("") == set()


def test_keywords_stop_words_filtered():
    kws = extract_keywords_from_content("this will have been that which are were")
    assert kws == set()


def test_keywords_max_keywords():
    kws = extract_keywords_from_content("alpha beta gamma delta epsilon zeta")
    assert len(kws) == 6


def test_keywords_limited():
    words = [f"word{chr(97+i)}" for i in range(50)]
    text = " ".join(words)
    kws = extract_keywords_from_content(text, max_keywords=10)
    assert len(kws) == 10


# ── extract_text_from_file ─────────────────────────

def test_extract_text_from_txt(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Hello world", encoding="utf-8")
    assert extract_text_from_file(f) == "Hello world"


def test_extract_text_from_unknown_ext(tmp_path):
    f = tmp_path / "test.bin"
    f.write_text("data", encoding="utf-8")
    assert extract_text_from_file(f) == ""


def test_extract_text_no_file():
    from textalchemy.core.exceptions import OrganizeError
    with pytest.raises(OrganizeError):
        extract_text_from_file("nonexistent.pdf")


# ── match_file_to_bibliography ─────────────────────

def test_match_manual_match():
    items = [BibItem(index=0, title="First"), BibItem(index=1, title="Second")]
    idx, text, score = match_file_to_bibliography(
        "content", "myfile.pdf", items,
        manual_matches={"myfile": 2},
    )
    assert idx == 1
    assert score == 1.0


def test_match_manual_match_out_of_range():
    items = [BibItem(index=0, title="First")]
    idx, text, score = match_file_to_bibliography(
        "content", "myfile.pdf", items,
        manual_matches={"myfile": 99},
    )
    assert score < 1.0


def test_match_no_items():
    idx, text, score = match_file_to_bibliography("content", "file.pdf", [])
    assert idx == -1
    assert score == 0.0


def test_match_low_score_below_threshold():
    items = [BibItem(index=0, title="About Power Transformers")]
    idx, text, score = match_file_to_bibliography(
        "completely unrelated text", "random.pdf", items, threshold=0.5,
    )
    assert idx == -1
    assert score < 0.5


def test_match_by_author_in_content():
    items = [BibItem(index=0, authors=["Ivanov"], title="Transformers Networks")]
    idx, text, score = match_file_to_bibliography(
        "Ivanov studied transformers in electrical networks",
        "paper.pdf", items,
    )
    assert idx == 0
    assert score > 0


def test_match_by_author_in_filename():
    items = [BibItem(index=0, authors=["Ivanov"], title="Power transformers")]
    idx, text, score = match_file_to_bibliography(
        "some content here", "ivanov_power_transformers.pdf", items,
    )
    assert idx == 0
    assert score > 0


def test_match_by_title_keywords():
    items = [BibItem(index=1, authors=["Ivanov"], title="Analysis of Power Transformers")]
    idx, text, score = match_file_to_bibliography(
        "Ivanov paper discusses analysis of power transformers in electrical networks",
        "analysis_power_transformers.pdf", items,
    )
    assert idx == 0
    assert score > 0


def test_match_year_boost():
    items = [BibItem(index=0, authors=["Ivanov"], title="Some Title Here", year=2020)]
    idx, text, score = match_file_to_bibliography(
        "Ivanov content 2020 more text", "paper.pdf", items,
    )
    assert idx == 0
    assert score > 0


def test_match_empty_content_with_title_in_filename():
    items = [BibItem(index=0, authors=["Smith"], title="Power System Analysis")]
    idx, text, score = match_file_to_bibliography(
        "", "power_system_analysis.pdf", items,
    )
    assert idx == 0
    assert score > 0


def test_match_author_not_found():
    items = [BibItem(index=0, authors=["Smith"], title="Title")]
    idx, _, score = match_file_to_bibliography(
        "random text unrelated", "file.pdf", items, threshold=0.5,
    )
    assert idx == -1


def test_match_best_score_selected():
    items = [
        BibItem(index=0, authors=["Ivanov"], title="Short"),
        BibItem(index=1, authors=["Petrov"], title="About Power Transformers in Networks"),
    ]
    content = "Petrov discusses power transformers and electrical networks"
    idx, text, score = match_file_to_bibliography(content, "file.pdf", items)
    assert idx == 1


def test_match_ignores_unknown_title():
    items = [BibItem(index=0, title="Unknown")]
    idx, text, score = match_file_to_bibliography("content", "file.pdf", items)
    assert idx == -1


def test_match_with_empty_items_list():
    idx, text, score = match_file_to_bibliography("content", "file.pdf", [])
    assert idx == -1
