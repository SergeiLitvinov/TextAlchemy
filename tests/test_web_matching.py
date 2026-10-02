"""Реальные сценарии: ручные соответствия, dry-run и ошибки копирования."""

import importlib
import json
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from textalchemy.core.database import Database
from textalchemy.core.types import BibItem
from textalchemy.web.main import app

MatchingFixture = tuple[TestClient, ModuleType, Path, Path]


@pytest.fixture
def matching(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MatchingFixture:
    web = importlib.import_module("textalchemy.web.app")
    data = tmp_path / "data"
    monkeypatch.setattr(web, "data_dir", data)
    monkeypatch.setattr(web, "db", Database(db_path=data / "library.db"))
    web.db.add_item(BibItem(index=40, title="Руководство по физике", authors=["Иванов И. И."], year=2020))
    source = tmp_path / "source"
    source.mkdir()
    (source / "Образец.TXT").write_text("abc", encoding="utf-8")
    output = tmp_path / "copies"
    web._save_config({"manual_matches": {"Образец": 1}, "keep": "metadata"})
    return TestClient(app), web, source, output


def run(client: TestClient, source: Path, output: Path, **kwargs: str) -> Response:
    return client.post(
        "/api/match/run",
        data={
            "source_dir": str(source),
            "output_dir": str(output),
            "threshold": "99",
            **kwargs,
        },
    )


def test_preview_and_copy_share_manual_override_and_keep_config(matching: MatchingFixture) -> None:
    client, web, source, output = matching
    preview = client.post("/api/preview/rename", data={"source_dir": str(source), "threshold": "99"}).json()
    assert preview["matched"] == 1
    assert not output.exists()
    result = run(client, source, output).json()
    assert result["success"] and result["errors"] == []
    row = result["matched"][0]
    assert row["match"] and row["copied"]
    assert row["new"] == preview["preview"][0]["new"] == row["planned_name"]
    assert Path(row["copied_path"]).read_text(encoding="utf-8") == "abc"
    assert Path(row["copied_path"]).suffix == ".txt"
    assert (source / "Образец.TXT").read_text(encoding="utf-8") == "abc"
    assert client.get("/api/match/report").json() == {key: value for key, value in result.items() if key != "success"}
    assert web._load_config()["manual_matches"] == {"Образец": 1}
    assert web._load_config()["keep"] == "metadata"


def test_dry_run_records_plan_without_claiming_copy(matching: MatchingFixture) -> None:
    client, _, source, output = matching
    result = run(client, source, output, dry_run="true").json()
    assert result["success"] and result["dry_run"]
    row = result["matched"][0]
    assert row["planned_name"] and row["new"] is None and row["copied_path"] is None
    assert not row["copied"] and not output.exists()


def test_failed_copy_retains_match_but_reports_failure_and_preserves_source(
    matching: MatchingFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, source, output = matching
    module = importlib.import_module("textalchemy.pipeline.match_files")

    def fail_copy(*args: object, **kwargs: object) -> None:
        raise PermissionError("Read-only destination")

    monkeypatch.setattr(module.shutil, "copy2", fail_copy)
    result = run(client, source, output).json()
    assert not result["success"] and result["errors"][0]["code"] == "copy_failed"
    row = result["matched"][0]
    assert row["match"] and row["planned_name"]
    assert row["new"] is None and not row["copied"] and row["copied_path"] is None
    assert list(output.iterdir()) == []
    assert (source / "Образец.TXT").read_text(encoding="utf-8") == "abc"


def test_external_bibliography_uses_same_manual_mapping(matching: MatchingFixture, tmp_path: Path) -> None:
    client, _, source, output = matching
    bibliography = tmp_path / "bib.txt"
    bibliography.write_text("Петров П. П. Другая книга. Москва: Издательство, 2021. 50 с.", encoding="utf-8")
    result = run(client, source, output, bibliography_file=str(bibliography), dry_run="true").json()
    assert len(result["matched"]) == 1
    assert "Петров" in result["matched"][0]["planned_name"]


def test_matching_service_is_usable_without_http(matching: MatchingFixture) -> None:
    _, web, source, _ = matching
    result = web.matching_service().preview(source_dir=str(source), threshold=99, bibliography_file="")
    assert result["matched"] == 1
    assert json.loads(web._config_path().read_text(encoding="utf-8"))["manual_matches"] == {"Образец": 1}
