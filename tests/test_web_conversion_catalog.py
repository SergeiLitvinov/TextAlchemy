"""Каталог отражает установленные возможности и поясняет новые направления."""

from __future__ import annotations

from pathlib import Path

from textalchemy.convert.executor import ConversionExecutor
from textalchemy.core.conversion_graph import CapabilityRegistry, ConverterCapabilities
from textalchemy.core.document_model import ConversionMode
from textalchemy.core.types import DocFormat
from textalchemy.web.services.conversion_catalog import available_conversions, resolve_conversion


def test_catalog_explains_new_formats_and_respects_dependencies() -> None:
    catalog = available_conversions(ConversionExecutor(requirement_checker=lambda _: True))
    sources = {source["format"]: source for source in catalog["sources"]}
    targets = {target["format"]: target for target in sources["epub"]["targets"]}
    assert sources["epub"]["default_target"] == "html"
    assert sources["txt"]["default_target"] == "docx"
    assert "редактируемые объекты" in " ".join(targets["pptx"]["guidance"])
    assert "Сложный CSS" in " ".join(targets["pptx"]["guidance"])
    assert "faithful" not in targets["pptx"]["modes"]
    assert "UTF-8" in " ".join(targets["txt"]["guidance"])
    restricted = available_conversions(ConversionExecutor(requirement_checker=lambda _: False))
    assert all(source["default_target"] in {target["format"] for target in source["targets"]} for source in restricted["sources"])
    assert all(target["format"] != "pptx" for source in restricted["sources"] for target in source["targets"])


def test_epub_has_a_default_web_destination() -> None:
    source, target = resolve_conversion(Path("book.epub"), source_format="auto", target_format="", legacy_format="")
    assert (source.value, target.value) == ("epub", "html")


def test_unavailable_dependency_and_unsupported_mode_are_distinct() -> None:
    catalog = available_conversions(ConversionExecutor(requirement_checker=lambda name: name != "python-pptx"))
    source = next(item for item in catalog["sources"] if item["format"] == "txt")
    target = next(item for item in source["unavailable_targets"] if item["format"] == "pptx")
    assert target["unavailable_modes"]["balanced"]["code"] == "missing_dependencies"
    assert target["unavailable_modes"]["balanced"]["requirements"] == ["python-pptx"]
    assert target["unavailable_modes"]["faithful"]["code"] == "unsupported_mode"
    assert "pptx" not in {item["format"] for item in source["targets"]}


def test_disconnected_handlers_do_not_hide_sources_or_claim_missing_dependencies() -> None:
    catalog = available_conversions(ConversionExecutor(handlers={}, requirement_checker=lambda _: True))
    assert catalog["sources"] == []
    source = next(item for item in catalog["unavailable_sources"] if item["format"] == "txt")
    target = next(item for item in source["unavailable_targets"] if item["format"] == "docx")
    assert target["unavailable_modes"]["balanced"]["code"] == "backend_unavailable"


def test_web_restriction_and_available_alternative() -> None:
    registry = CapabilityRegistry()
    modes = frozenset({ConversionMode.BALANCED})
    for name, source, target in (("first", DocFormat.TXT, DocFormat.DOCX), ("second", DocFormat.DOCX, DocFormat.HTML)):
        registry.register(ConverterCapabilities(name, source, target, modes, {}))
    executor = ConversionExecutor(registry=registry, handlers={"first": None, "second": None})
    catalog = available_conversions(executor)
    source = next(item for item in catalog["sources"] if item["format"] == "txt")
    target = next(item for item in source["unavailable_targets"] if item["format"] == "html")
    assert target["unavailable_modes"]["balanced"]["code"] == "web_route_unsupported"
    registry.register(ConverterCapabilities("direct", DocFormat.TXT, DocFormat.HTML, modes, {}, requirements=("optional-tool",)))
    registry.register(ConverterCapabilities("fallback", DocFormat.TXT, DocFormat.HTML, modes, {}))
    executor.backends.update({"direct": None, "fallback": None})
    executor.requirement_checker = lambda _: False
    catalog = available_conversions(executor)
    source = next(item for item in catalog["sources"] if item["format"] == "txt")
    target = next(item for item in source["targets"] if item["format"] == "html")
    assert target["plans"]["balanced"]["steps"] == ["fallback"]
    assert "balanced" not in target["unavailable_modes"]
