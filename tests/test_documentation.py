"""Documentation checks must fail on drift, broken examples and unsafe links."""

import pytest

from tools.documentation import checks, generated, site


def test_generated_reference_drift_requires_explicit_regeneration(tmp_path, monkeypatch):
    monkeypatch.setattr(generated, "ROOT", tmp_path)
    monkeypatch.setattr(generated, "pages", lambda: {"docs/reference/cli.md": "# New command\n"})
    generated.sync()
    generated.sync(check=True)
    path = tmp_path / "docs/reference/cli.md"
    path.write_text("# Outdated command\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Устарели справочники"):
        generated.sync(check=True)
    assert path.read_text(encoding="utf-8") == "# Outdated command\n"


def test_invalid_command_in_prose_is_rejected():
    with pytest.raises(ValueError, match="Неверная команда"):
        checks.check_commands("```powershell\nuv run textalchemy convert-file in.txt out.docx --invented-option\n```")


def test_site_links_preserve_unicode_anchors_and_copy_linked_source(tmp_path, monkeypatch):
    monkeypatch.setattr(site, "ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/next.md").write_text("# Пример", encoding="utf-8")
    (tmp_path / "code.py").write_text("value = 1", encoding="utf-8")
    assets = {}
    rendered = site.rewrite_links("[Глава](next.md#пример) [Код](../code.py)", "docs/start.md", {"docs/next.md": ""}, assets)
    assert rendered == "[Глава](next.md#пример) [Код](../files/code.py)"
    assert assets == {"files/code.py": b"value = 1"}


def test_site_rejects_links_outside_repository(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    root.mkdir()
    (tmp_path / "private.txt").write_text("outside", encoding="utf-8")
    monkeypatch.setattr(site, "ROOT", root)
    with pytest.raises(ValueError, match="invalid local link"):
        site.rewrite_links("[File](../private.txt)", "README.md", {}, {})


def test_duplicate_or_missing_migration_entry_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "ROOT", tmp_path)
    history = tmp_path / "docs/history"
    history.mkdir(parents=True)
    (history / "todo-2026-09-13.md").write_text("- [x] First\n- [ ] Second\n", encoding="utf-8")
    mapping = history / "todo-milestone-map.md"
    mapping.write_text("| L1 | done |\n| L1 | done |", encoding="utf-8")
    with pytest.raises(ValueError, match="пропуски или дубликаты"):
        checks.check_mapping()
    mapping.write_text("| L2 | open |\n| L1 | done |", encoding="utf-8")
    assert checks.check_mapping() == 2
