"""The Web runtime avoids fork while respecting existing safe contexts."""

import pytest

from textalchemy.web import runtime


@pytest.mark.parametrize("existing", [None, "fork", "spawn", "forkserver"])
def test_web_startup_selects_a_safe_worker_context(monkeypatch, existing):
    changes = []
    monkeypatch.setattr(runtime.multiprocessing, "get_start_method", lambda *, allow_none: existing)
    monkeypatch.setattr(
        runtime.multiprocessing, "set_start_method", lambda method, *, force: changes.append((method, force))
    )

    selected = runtime.configure_worker_processes()

    assert selected != "fork"
    if existing in (None, "fork"):
        assert selected == "spawn"
        assert changes == [("spawn", True)]
    else:
        assert selected == existing
        assert changes == []
