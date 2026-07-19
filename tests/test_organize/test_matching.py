import json

from textalchemy.core.types import DocFormat, Document, Text
from textalchemy.organize import load_manual_matches
from textalchemy.organize.bibliography import BibItem as OrgBibItem
from textalchemy.pipeline.match import match_bibliography


def _doc(path: str) -> Document:
    return Document(path=path, format=DocFormat.UNKNOWN, size=0, sha256="")


def _text(plain: str) -> Text:
    return Text(plain=plain)


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


# ── match_bibliography (new signal-based engine) ───

def test_match_manual_match():
    items = [OrgBibItem(index=0, title="First"), OrgBibItem(index=1, title="Second")]
    doc = _doc("myfile.pdf")
    m = match_bibliography(text=_text("content"), document=doc, items=items,
                           manual={"myfile": 2})
    assert m.matched
    assert m.item is items[1]


def test_match_manual_match_out_of_range():
    items = [OrgBibItem(index=0, title="First")]
    doc = _doc("myfile.pdf")
    m = match_bibliography(text=_text("content"), document=doc, items=items,
                           manual={"myfile": 99})
    assert not m.matched


def test_match_no_items():
    doc = _doc("file.pdf")
    m = match_bibliography(text=_text("content"), document=doc, items=[])
    assert not m.matched


def test_match_low_score_below_threshold():
    items = [OrgBibItem(index=0, title="About Power Transformers")]
    doc = _doc("random.pdf")
    m = match_bibliography(text=_text("completely unrelated text"), document=doc,
                           items=items, threshold=0.5)
    assert not m.matched


def test_match_by_author_in_content():
    items = [OrgBibItem(index=0, authors=["Ivanov"], title="Transformers Networks")]
    doc = _doc("paper.pdf")
    m = match_bibliography(text=_text("Ivanov studied transformers in electrical networks"),
                           document=doc, items=items)
    assert m.matched
    assert m.item is items[0]


def test_match_by_author_in_filename():
    items = [OrgBibItem(index=0, authors=["Ivanov"], title="Power transformers")]
    doc = _doc("ivanov_power_transformers.pdf")
    m = match_bibliography(text=_text("some content here"), document=doc, items=items)
    assert m.matched


def test_match_by_title_keywords():
    items = [OrgBibItem(index=1, authors=["Ivanov"], title="Analysis of Power Transformers")]
    doc = _doc("analysis_power_transformers.pdf")
    m = match_bibliography(
        text=_text("Ivanov paper discusses analysis of power transformers in electrical networks"),
        document=doc, items=items,
    )
    assert m.matched


def test_match_year_boost():
    items = [OrgBibItem(index=0, authors=["Ivanov"], title="Some Title Here", year=2020)]
    doc = _doc("paper.pdf")
    m = match_bibliography(text=_text("Ivanov content 2020 more text"), document=doc, items=items)
    assert m.matched


def test_match_empty_content_with_title_in_filename():
    items = [OrgBibItem(index=0, authors=["Smith"], title="Power System Analysis")]
    doc = _doc("power_system_analysis.pdf")
    m = match_bibliography(text=_text(""), document=doc, items=items)
    assert m.matched


def test_match_author_not_found():
    items = [OrgBibItem(index=0, authors=["Smith"], title="Title")]
    doc = _doc("file.pdf")
    m = match_bibliography(text=_text("random text unrelated"), document=doc, items=items,
                           threshold=0.5)
    assert not m.matched


def test_match_best_score_selected():
    items = [
        OrgBibItem(index=0, authors=["Ivanov"], title="Short"),
        OrgBibItem(index=1, authors=["Petrov"], title="About Power Transformers in Networks"),
    ]
    doc = _doc("file.pdf")
    content = "Petrov discusses power transformers and electrical networks"
    m = match_bibliography(text=_text(content), document=doc, items=items)
    assert m.matched
    assert m.item is items[1]


def test_match_ignores_unknown_title():
    items = [OrgBibItem(index=0, title="Unknown")]
    doc = _doc("file.pdf")
    m = match_bibliography(text=_text("content"), document=doc, items=items)
    assert not m.matched


def test_match_with_empty_items_list():
    doc = _doc("file.pdf")
    m = match_bibliography(text=_text("content"), document=doc, items=[])
    assert not m.matched
