"""Архитектурные ограничения Web-слоя против повторного появления god-файлов."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1] / "src" / "textalchemy" / "web"


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _branch_complexity(node: ast.AST) -> int:
    branch_nodes = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.IfExp, ast.Match, ast.comprehension)
    return 1 + sum(isinstance(child, branch_nodes) for child in ast.walk(node))


@pytest.mark.parametrize("path", sorted((ROOT / "routes").glob("*.py")), ids=lambda path: path.name)
def test_web_route_size_budget(path: Path):
    assert _lines(path) <= 450, f"{path.name}: route смешивает слишком много обязанностей"


@pytest.mark.parametrize("path", sorted((ROOT / "services").glob("*.py")), ids=lambda path: path.name)
def test_web_service_size_budget(path: Path):
    assert _lines(path) <= 250, f"{path.name}: application service требует декомпозиции"


@pytest.mark.parametrize(
    "path",
    sorted([*(ROOT / "routes").glob("*.py"), *(ROOT / "services").glob("*.py")]),
    ids=lambda path: str(path.relative_to(ROOT)),
)
def test_web_function_complexity_budget(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    offenders = {node.name: _branch_complexity(node) for node in functions if _branch_complexity(node) > 20}
    assert not offenders, f"{path.name}: функции смешивают слишком много ветвей: {offenders}"


def test_web_routes_do_not_own_background_queue_implementation():
    for path in (ROOT / "routes").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "ThreadPoolExecutor" not in source
        assert "TaskStore(" not in source
        assert "ArtifactWorkspace(" not in source


@pytest.mark.parametrize("path", sorted((ROOT / "templates").glob("*.html")), ids=lambda path: path.name)
def test_web_template_size_budget(path: Path):
    assert _lines(path) <= 300, f"{path.name}: presentation template требует partials/components"


@pytest.mark.parametrize(
    "path",
    sorted((ROOT / "static" / "js" / "pages").rglob("*.js")),
    ids=lambda path: str(path.relative_to(ROOT)),
)
def test_web_page_controller_size_budget(path: Path):
    assert _lines(path) <= 450, f"{path.name}: page controller требует разделения по компонентам"


def test_conversion_es_modules_keep_dependency_direction():
    modules = ROOT / "static" / "js" / "pages" / "convert"
    assert modules.is_dir()
    for path in modules.glob("*.js"):
        source = path.read_text(encoding="utf-8")
        assert _lines(path) <= 300, f"{path.name}: компонент конвертации получил слишком много обязанностей"
        assert "../convert.js" not in source, f"{path.name}: компонент не должен импортировать page controller"


def test_pipeline_es_modules_keep_dependency_direction():
    modules = ROOT / "static" / "js" / "pages" / "pipeline"
    assert modules.is_dir()
    for path in modules.glob("*.js"):
        source = path.read_text(encoding="utf-8")
        assert _lines(path) <= 200, f"{path.name}: компонент pipeline получил слишком много обязанностей"
        assert "../pipeline.js" not in source, f"{path.name}: компонент не должен импортировать page controller"


def test_core_does_not_depend_on_delivery_or_infrastructure_layers():
    source = ROOT.parent
    forbidden = ("textalchemy.web", "textalchemy.cli", "textalchemy.convert", "textalchemy.recognize")
    for path in (source / "core").rglob("*.py"):
        invalid = sorted(name for name in _imports(path) if name.startswith(forbidden))
        assert not invalid, f"{path.name}: core зависит от внешнего слоя: {invalid}"


def test_web_services_do_not_depend_on_routes_or_templates():
    for path in (ROOT / "services").rglob("*.py"):
        invalid = sorted(name for name in _imports(path) if name.startswith("textalchemy.web.routes"))
        assert not invalid, f"{path.name}: application service зависит от presentation routes: {invalid}"


@pytest.mark.parametrize("name", ["matching", "pipeline", "extract", "recognize", "convert_jobs", "convert_preview"])
def test_matching_and_pipeline_routes_only_adapt_http(name: str) -> None:
    path = ROOT / "routes" / f"{name}.py"
    imports = _imports(path)
    assert not any(item.startswith(("textalchemy.pipeline", "textalchemy.organize", "textalchemy.core")) for item in imports)
    source = path.read_text(encoding="utf-8")
    assert ".rglob(" not in source and ".all_items(" not in source


@pytest.mark.parametrize("name", ["matching", "pipeline_builder", "bibliography_export", "generator_catalog",
                                  "generator_execution", "generator_sessions", "extraction", "recognition",
                                  "upload_input", "documentation", "batch_submission", "batch_retry", "batch_history",
                                  "conversion_preview", "conversion_inspection", "conversion_submission"])
def test_matching_pipeline_and_export_services_do_not_import_http_or_application_state(name: str) -> None:
    imports = _imports(ROOT / "services" / f"{name}.py")
    assert not any(item.startswith(("fastapi", "starlette", "textalchemy.web.app")) for item in imports)


def test_generator_route_delegates_execution_and_dataset_validation() -> None:
    source = (ROOT / "routes" / "generate.py").read_text(encoding="utf-8")
    assert "service.generate(" in source and "GeneratorDatasetService(" in source
    assert "validate_snapshot(" not in source and "validate_template_data(" not in source
    assert "workspace.artifact_path(" not in source and "workspace.cleanup(" not in source


def test_page_routes_delegate_context_queries_to_application_service():
    path = ROOT / "routes" / "pages.py"
    source = path.read_text(encoding="utf-8")
    imports = _imports(path)
    assert "textalchemy.web.services.page_context" in imports
    assert "json" not in imports
    assert "pathlib" not in imports
    assert ".rglob(" not in source


def test_global_task_center_keeps_store_projection_out_of_http_adapter():
    route = (ROOT / "routes" / "task_center.py").read_text(encoding="utf-8")
    service = (ROOT / "services" / "task_center.py").read_text(encoding="utf-8")
    assert "TaskCenterService" in route
    assert ".list_tasks(" not in route
    assert ".list_tasks(" in service
    assert "/cancel" in route and "/rerun" in route
    assert "can_cancel" in service and "can_rerun" in service


def test_conversion_pipeline_has_typed_stage_and_extension_contracts():
    stages = ROOT.parent / "convert" / "stages.py"
    source = stages.read_text(encoding="utf-8")
    assert "class StageKind" in source
    stage_names = ("PARSE", "NORMALIZE", "LAYOUT", "RESOURCES", "SERIALIZE", "VERIFY")
    assert all(f'{name} = "{name.lower()}"' in source for name in stage_names)
    assert "class ConversionStage" in source
    assert "class FormatExtension" in source


def test_large_conversion_modules_have_documented_decomposition_budget():
    source = ROOT.parent
    budgets = {
        source / "convert" / "executor.py": 400,
        source / "formats" / "docx.py": 400,
        source / "formats" / "pdf_geometry.py": 400,
        source / "formats" / "pdf_ocr_merge.py": 450,
    }
    for path, limit in budgets.items():
        assert _lines(path) <= limit, f"{path.name}: orchestration module exceeds {limit} lines"


def test_conversion_module_size_budget_has_explicit_legacy_allowlist():
    source = ROOT.parent
    legacy_limits = {
        "convert/html_writer.py": 1900,  # chart renderers are pure serialization helpers
        "convert/pptx_to_html/_renderer.py": 1800,  # compatibility renderer with embedded viewer assets
        "formats/pptx.py": 1750,  # XML importer; new work must move behind stage adapters
    }
    for folder in (source / "convert", source / "formats"):
        for path in folder.rglob("*.py"):
            relative = path.relative_to(source).as_posix()
            limit = legacy_limits.get(relative, 600)
            assert _lines(path) <= limit, f"{relative}: exceeds explicit module budget {limit}"


def test_shared_shell_features_live_in_components():
    components = ROOT / "static" / "js" / "components"
    assert (components / "task-center.js").is_file()
    app_source = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "/api/tasks" not in app_source


def test_theme_uses_semantic_tokens_without_inline_palette():
    css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
    app_source = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert ':root[data-theme="dark"]' in css
    for token in ("--surface-raised", "--text-strong", "--on-primary", "--danger-soft", "--document-paper"):
        assert css.count(token) >= 2, f"{token}: token must exist in both themes"
    assert "style.setProperty" not in app_source
    assert "dataset.theme" in app_source


def test_localization_is_catalog_driven_not_duplicated_templates():
    route = (ROOT / "routes" / "localization.py").read_text(encoding="utf-8")
    service = (ROOT / "services" / "localization.py").read_text(encoding="utf-8")
    client = (ROOT / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    assert "locale_catalog" in route
    assert "SUPPORTED_LOCALES" in service
    assert "[data-i18n]" in client


def test_web_python_import_graph_has_no_cycles():
    modules = {}
    for path in ROOT.rglob("*.py"):
        name = "textalchemy.web." + ".".join(path.relative_to(ROOT).with_suffix("").parts)
        name = name.removesuffix(".__init__")
        if name in {"textalchemy.web", "textalchemy.web.main"}:
            continue  # public composition roots intentionally aggregate the package and route modules
        modules[name] = _imports(path)
    graph = {
        name: {dependency for dependency in dependencies if dependency in modules and dependency != name}
        for name, dependencies in modules.items()
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str, trail: list[str]) -> None:
        if name in visiting:
            cycle = " → ".join([*trail[trail.index(name) :], name])
            pytest.fail(f"Циклическая зависимость Web-модулей: {cycle}")
        if name in visited:
            return
        visiting.add(name)
        for dependency in graph[name]:
            visit(dependency, [*trail, name])
        visiting.remove(name)
        visited.add(name)

    for module in graph:
        visit(module, [])


@pytest.mark.parametrize(
    "name",
    [
        "bibliography.html",
        "convert.html",
        "export.html",
        "extract.html",
        "generate.html",
        "matching.html",
        "pipeline.html",
        "recognize.html",
        "reports.html",
    ],
)
def test_redesigned_templates_do_not_contain_inline_controllers(name: str):
    assert "<script>" not in (ROOT / "templates" / name).read_text(encoding="utf-8")
