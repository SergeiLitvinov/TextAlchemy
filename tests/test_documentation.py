"""Documentation checks must fail on drift, broken examples and unsafe links."""

import pytest

from tools.documentation import checks, generated, site
from tools.documentation.navigator import code_pages, user_guide


@pytest.mark.parametrize(
    "text",
    [
        "## M7. Architecture\n- [x] **M7.1:** Complete",
        "## M7. Architecture\n- [ ] **M7.1:** First\n- [ ] **M7.1:** Duplicate",
        "## M7. Architecture\n- [ ] **M6.1:** Wrong owner",
        "## Other\n- [ ] **M7.1:** No milestone",
        "## M7. Architecture\n- [ ] No ID",
    ],
)
def test_active_plan_rejects_completed_duplicate_and_unowned_work(text: str) -> None:
    with pytest.raises(ValueError):
        checks.check_active_plan(text)


def test_active_plan_accepts_only_remaining_milestone_tasks() -> None:
    assert checks.check_active_plan("# План\nОставшихся задач нет.") == 0
    assert (
        checks.check_active_plan(
            "## M7. Architecture\n- [ ] **M7.1 (A1):** Service\n## M6. Quality\n- [ ] **M6.2 (Q2):** New budget"
        )
        == 2
    )


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
    assert rendered == "[Глава](next.md#пример) [Код](../files/code.py.html)"
    assert b'id="L1"' in assets["files/code.py.html"]
    assert b"value = 1" in assets["files/code.py.html"]


def test_source_view_escapes_executable_markup(tmp_path):
    path = tmp_path / "source.html"
    path.write_text("<script>alert(1)</script>", encoding="utf-8")
    content = site.source_page(path, "source.html").decode("utf-8")
    assert "<script>" not in content
    assert "&lt;script&gt;" in content


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


def test_code_navigator_uses_static_sources_and_tracks_new_routes(tmp_path):
    source = tmp_path / "src/textalchemy"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("", encoding="utf-8")
    (source / "model.py").write_text("class Document: pass\n", encoding="utf-8")
    routes = source / "web/routes.py"
    routes.parent.mkdir()
    routes.write_text(
        'from ..model import Document\nraise RuntimeError("must not import")\n@app.get("/example")\nasync def handler(): pass\n',
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_example.py").write_text("from textalchemy.model import Document\n", encoding="utf-8")
    result = code_pages(tmp_path, "")
    assert "textalchemy.model](#textalchemy-model)" in result["docs/reference/code.md"]
    assert "test_example.py" in result["docs/reference/code.md"]
    assert "| GET | `/example`" in result["docs/reference/web-routes.md"]
    assert code_pages(tmp_path, "") == result
    routes.write_text(routes.read_text(encoding="utf-8").replace("/example", "/changed"), encoding="utf-8")
    assert "| GET | `/changed`" in code_pages(tmp_path, "")["docs/reference/web-routes.md"]


def test_manual_navigation_follows_real_headings_only(tmp_path):
    guide = tmp_path / "docs/guide"
    guide.mkdir(parents=True)
    for name in ("index.md", "formats.md", "web-details.md"):
        (guide / name).write_text("# Руководство\n## Создать документ\n```text\n## Не глава\n```\n", encoding="utf-8")
    content = user_guide(tmp_path, "")
    assert "../guide/index.md#создать-документ" in content
    assert "Не глава" not in content


def test_cleanup_preserves_data_and_has_preview(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from tools import clean

    monkeypatch.setattr(clean.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=b""))
    disposable = tmp_path / "src/package/__pycache__/module.pyc"
    protected = [
        tmp_path / ".textalchemy/library.db",
        tmp_path / "tmp/user.pdf",
        tmp_path / ".venv/lib/__pycache__/module.pyc",
        tmp_path / "src/package/main.py",
    ]
    for path in [disposable, *protected]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"preserved")
    preview = clean.clean(tmp_path)
    assert preview["bytes"] == disposable.stat().st_size
    assert disposable.exists()
    clean.clean(tmp_path, apply=True)
    assert not disposable.exists()
    assert all(path.read_bytes() == b"preserved" for path in protected)


def test_cleanup_rejects_tracked_files_before_deleting(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from tools import clean

    monkeypatch.setattr(clean.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=b".coverage\0"))
    (tmp_path / ".coverage").write_text("tracked", encoding="utf-8")
    (tmp_path / ".pytest_cache").mkdir()
    with pytest.raises(ValueError, match="Tracked files"):
        clean.clean(tmp_path, apply=True)
    assert (tmp_path / ".pytest_cache").exists()
    with pytest.raises(ValueError, match="Outside cleanup scope"):
        clean.safe_tree(tmp_path.parent, tmp_path)
