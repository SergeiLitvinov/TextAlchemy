"""Accept published EPUB table/MathML support through the application's API."""

import pytest

from tests import test_web_m4_completion as fixtures
from tests.corpus.epub_fixture import write_epub_fixture
from textalchemy.core.document_codec import document_from_json
from textalchemy.core.document_model import Formula, FormulaFormat, Table
from textalchemy.web.queue import task_queue

m4_client = fixtures.m4_client


def book(path, *, span="2"):
    write_epub_fixture(path, title="Structures", language="en", chapters=[(
        "chapters/main.xhtml", "Main",
        '<html xmlns="http://www.w3.org/1999/xhtml"><body><table id="results"><caption>Results</caption>'
        f'<tr><td rowspan="{span}">A <b>B</b> C</td><td>12</td></tr>'
        '<tr><td><table><tr><td>Nested</td></tr></table></td></tr></table><p>Equation '
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi><mo>+</mo><mn>1</mn></math></p>'
        '<script>Never paragraph text</script></body></html>',
    )])


def convert(client, content, name, target, **policy):
    response = client.post("/api/convert", files={"file": (name, content)}, data={"target_format": target, **policy})
    assert response.status_code == 200, response.text
    assert task_queue.wait_idle(timeout=30)
    task = response.json()
    return client.get(task["status"]).json()["report"], client.get(task["result"])


@pytest.mark.parametrize("target", ["model", "html"])
def test_table_formula_and_json_reimport(m4_client, tmp_path, target):
    client, _ = m4_client
    source = tmp_path / "structures.epub"
    book(source)
    original = source.read_bytes()
    report, model = convert(client, original, source.name, "model")
    assert report["success"] and model.status_code == 200
    for _ in range(2):
        blocks = document_from_json(model.text).sections[0].blocks
        assert blocks[0].plain_text == "Results"
        table = blocks[1]
        assert isinstance(table, Table) and table.rows[0].cells[0].row_span == 2
        paragraph = table.rows[0].cells[0].blocks[0]
        assert paragraph.plain_text == "A B C" and paragraph.content[1].style.bold
        nested = table.rows[1].cells[0].blocks[0]
        assert isinstance(nested, Table) and nested.rows[0].cells[0].blocks[0].plain_text == "Nested"
        formula = blocks[2].content[1]
        assert isinstance(formula, Formula) and formula.format is FormulaFormat.MATHML
        assert formula.fallback_text == "x+1" and not formula.display
        assert table.provenance.package_part == formula.provenance.package_part == "/chapters/main.xhtml"
        assert "Never paragraph text" not in "".join(block.plain_text for block in blocks if hasattr(block, "plain_text"))
        report, output = convert(client, model.content, "structures.json", target)
        assert report["success"] and output.status_code == 200
        if target == "model":
            model = output
        else:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(output.text, "html.parser")
            assert len(soup.find_all("table")) == 2
            assert soup.find("td", rowspan="2").get_text() == "A B C"
            assert soup.find("math") is not None
    assert source.read_bytes() == original


def test_invalid_span_loss_survives_json_and_strict_budget(m4_client, tmp_path):
    client, _ = m4_client
    source = tmp_path / "invalid.epub"
    book(source, span="bad")
    original = source.read_bytes()
    report, model = convert(client, original, source.name, "model")
    assert report["success"] and not report["lossless"]
    issue = next(item for item in report["metrics"]["step_metrics"]["epub.model"]["import_diagnostics"]
                 if item["reason"] == "invalid-cell-span")
    assert issue["severity"] == "loss" and issue["location"]
    for content, name in [(original, source.name), (model.content, "invalid.json")]:
        strict, result = convert(client, content, name, "html", max_loss_issues="0")
        assert not strict["success"] and strict["metrics"]["quality_gate"]["loss_issues"] > 0
        assert result.status_code == 409
    assert source.read_bytes() == original
