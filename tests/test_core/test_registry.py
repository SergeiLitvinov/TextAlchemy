"""Тесты core.registry."""
from __future__ import annotations

import pytest

from textalchemy.core.registry import all_operations, by_tag, get, isolated, operation


def test_operation_registers():
    with isolated():

        @operation("test.op1", description="demo")
        def op1(x: int) -> int:
            return x

        spec = get("test.op1")
        assert spec.id == "test.op1"
        assert spec.func is op1
        assert spec.description == "demo"


def test_duplicate_raises():
    with isolated():

        @operation("test.dup")
        def a():
            return 1

        with pytest.raises(ValueError):

            @operation("test.dup")
            def b():
                return 2


def test_unknown_raises():
    with pytest.raises(KeyError):
        get("does.not.exist")


def test_all_operations_lists_everything():
    with isolated():

        @operation("test.one")
        def one():
            return 1

        @operation("test.two", tags=["extract"])
        def two():
            return 2

        ids = {s.id for s in all_operations()}
        assert {"test.one", "test.two"} <= ids


def test_by_tag():
    with isolated():

        @operation("test.tagged", tags=["extract", "v1"])
        def f():
            return 1

        @operation("test.untagged")
        def g():
            return 2

        tagged = by_tag("extract")
        assert [s.id for s in tagged] == ["test.tagged"]


def test_pipeline_operations_survive_isolation():
    """Импорт pipeline.ingest должен регистрировать ingest.file; isolated() не должен его убивать."""
    from textalchemy.pipeline.ingest import ingest_file  # noqa: F401

    assert any(s.id == "ingest.file" for s in all_operations())

    with isolated():
        # внутри — реестр пуст, но это нормально
        assert all_operations() == []
    # после isolated() — снова видим ingest.file
    assert any(s.id == "ingest.file" for s in all_operations())
