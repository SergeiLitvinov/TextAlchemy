# AGENTS.md

TextAlchemy — Python toolkit for scientific/educational document processing. Application plus independently installable document and format-adapter libraries; one application CLI entry point.

## Layout

The generated [code navigator](../reference/code.md) is the source of truth for module paths, public definitions, internal imports and direct test imports. [Web routes](../reference/web-routes.md) maps request paths to handlers. Regenerate these instead of maintaining a second file inventory here.

Start with these stable entry points:

| Work | Entry point |
|---|---|
| CLI parsing and dispatch | `src/textalchemy/__main__.py`, handlers under `src/textalchemy/cli/` |
| Document structures | Independent OpenDoc project at `C:/project/opendoc`; bundled dependency in `vendor/opendoc/`; compatibility imports under `src/textalchemy/core/` |
| Application operations | `src/textalchemy/pipeline/` |
| Format import/export | Independent `C:/project/opendoc-formats`; wheel in `vendor/opendoc-formats/`; compatibility imports under `src/textalchemy/formats/`, `src/textalchemy/convert/`, `src/textalchemy/extract/latex.py`; route execution stays in the application |
| Template generation | In-memory API under `src/textalchemy/templating/`; application file/export adapters under `src/textalchemy/generate/` |
| Web behavior | `src/textalchemy/web/routes/`, `services/`, `static/js/pages/` |
| Reproducible fixtures | [Corpus](corpus.md), [Office provenance](office-corpus.md) |

The sections below define contributor contracts and workflows; implementation inventory belongs to the navigator, user behavior to the guide, and future work to doc/development/roadmap.md (root TODO.md is its pointer).

## Commands

Always run via `uv` so the lockfile-resolved env is used.

- Install (full): `uv sync --all-extras`
- Minimal install: `uv sync` (yaml, platformdirs, jinja2, tqdm; OpenDoc Formats extras `pdf-text` and `fonts` retain lightweight PDF extraction/font support). Format extras `pdf`, `docx`, `pptx`, `epub`, `html` select the corresponding OpenDoc Formats extras; that library owns engine requirements. Application extras own Web, OCR and raster comparison dependencies. Readers/converters lazy-import their backends and never force them at `import textalchemy`.
- Lint: `uv run ruff check` (configuration is defined in `pyproject.toml`)
- Format: `uv run ruff check --fix && uv run ruff format`
- Test: `uv run pytest tests/ -v --tb=short` (or `--cov=textalchemy` for application coverage). Coverage threshold `--cov-fail-under=80` is enforced whenever `--cov` is active (see `pyproject.toml`). OpenDoc and OpenDoc Formats tests and coverage belong to their own projects; application CI checks the published wheel and integration contracts.
- Single test: `uv run pytest tests/test_pipeline/test_runner.py::test_run_chained_ingest_extract -v`
- Pipeline run: `uv run textalchemy run pipeline.yaml` (or `textalchemy run --list`, `--json` for JSON output)
- Most commands support `--json` for structured machine-readable output (`extract`, `convert`, `convert-file`, `plan`, `inspect`, `template-check`, `pptx2html`, `gost`, `stats`, `generate`, `bibtex`, `recognize`, `match`, `run`)
- Web UI: `uv run textalchemy web` (defaults 127.0.0.1:8000)
- OCR: `uv run textalchemy recognize input.pdf --backend paddle --gpu --mode handwriting --output result.docx`
- CLI entry: `textalchemy = textalchemy.__main__:main` (see `pyproject.toml`)

Equivalent `make` targets exist in the `Makefile` (`make install|test|lint|format|coverage|web`).

## CI

Documentation lives in [guide](../guide/index.md), [generated reference](../reference/cli.md), and [verification](../guide/verification.md); [roadmap](roadmap.md) is the only active milestone plan; root `TODO.md` links to it. Update the relevant guide chapter and milestone when behavior changes. Do not hand-edit `doc/reference/`: run `uv run python -m tools.docs generate` after CLI or operation changes, then `uv run python -m tools.docs check` (extra `docs` plus the example dependencies). Local preview: `uv run python -m tools.docs serve`. See [documentation workflow](documentation.md). CI checks reference drift, links, dependency inventory and active-plan structure and runnable examples, then stores the built site as an artifact.

Generated documentation also includes [user-guide navigation](../reference/user-guide.md), [code navigator](../reference/code.md) and [Web routes](../reference/web-routes.md). Regenerate after Python source, Web file inventory, test imports or guide headings change. The navigator uses static AST inspection; test links are not coverage claims. Use `uv run python -m tools.clean` to preview reproducible cache cleanup, and add `--apply` to remove only that allowlist; never clean the entire `.textalchemy` data directory.

The application serves its bundled documentation at `/help/`. `tools.docs generate` builds the site and updates `src/textalchemy/web/assets/documentation.zip`; `build` and `check` reject a stale bundle. Regenerate after documentation or theme changes as well. The archive is a distribution asset, not a user-data cache; runtime does not require MkDocs or access to the source checkout.

`.github/workflows/ci.yml` runs on Python 3.11/3.12/3.13: a frozen developer profile (dev/docs/web/pdf/docx/pptx/html/epub) → `uv run ruff check` → `uv run pytest tests/ --cov=textalchemy --cov-report=xml` (uploads to codecov). All browser tests run with Chromium on every matrix version. CI verifies release archives and publishes checked documentation to GitHub Pages; release.yml performs versioned publication. Required order: install → lint → test. A separate job verifies the bundled document wheel without the application. OpenDoc owns its source, tests, coverage and build CI. See [library workflow](document-library.md).

## Operation contract (pipeline/)

Every operation is `@operation("id", input_type=..., output_type=..., input_param=..., tags=[...])`. Strict contract:

1. **All parameters are keyword-only** — `def render_latex(*, text: Text, title: str = "Document"): ...`. The runner calls operations with `**kwargs` only, so positional-only parameters will fail.
2. **`input_param` declares the input kwarg name** (default `"input"`). The runner resolves a step's `input: ctx_name` field into `params[input_param]`.
3. **Return values are JSON-serializable OR `Path`/`Document`/`Text`/`Match`/`BibItem`/`DocumentModel`** — anything else breaks `--json` output and `RunResult.to_dict()`. `DocumentModel` is serialized via `document_to_dict` (see `pipeline/runner.py:_safe`).
4. **The function name in tests should be invoked as `func(name=value, ...)`** — never positionally.

The registry exposes `all_operations()`, `get(id)`, `by_tag(tag)`, `isolated()` (context manager for tests). Use `from textalchemy.core.registry import isolated` to test the registry without polluting the global state — `reset()` is destructive and removes `pipeline.*` operations from the registry, breaking other tests.

## Pipeline runner (YAML/TOML/JSON)

```yaml
steps:
  - op: ingest.file
    output: doc
    params: {path: input.txt}
  - op: extract.text
    input: doc
    output: text
  - op: render.latex
    input: text
    output: tex
    params: {title: "Demo"}
output: tex            # final value; defaults to last step's output
```

- `output:` per step writes the result into `ctx[name]`.
- `input: name` looks up `ctx[name]` and binds it to the op's `input_param`.
- `params: {x: $y}` substitutes `ctx["y"]` (the `$` prefix is mandatory).
- `params: {x: "{title}"}` runs `str.format(**ctx)`.
- Top-level fields outside `steps:`/`output:` populate the initial `ctx`.
- Top-level `bib: [...]` is a convenient way to pass `BibItem[]` to render ops. The `render.*` ops accepting `BibItem[]` auto-normalize `dict` items via `_normalize_items` (see `pipeline/render.py`).

Run `textalchemy run --list` to see all registered operations.

## Adding a new CLI subcommand

1. Add a parser in `_setup_parser()` and a `case` arm in `main()` in `src/textalchemy/__main__.py`.
2. Implement `cmd_<name>(args)` in a new module under `src/textalchemy/cli/` (named `<name>_cmd.py`).
3. Re-export from `src/textalchemy/cli/__init__.py` and import in `__main__.py`.
4. If the command supports `--json`, add the flag to the parser and check `args.json` in the handler.
5. Add tests in `tests/test_cli.py` following the existing style (use `main([...])` directly, not the installed `textalchemy` script).

## Adding a new pipeline operation

1. Create or extend a module under `src/textalchemy/pipeline/`.
2. Decorate with `@operation("namespace.op", input_type=..., output_type=..., input_param=..., tags=[...])`. The function signature must be **keyword-only** and the input kwarg name must match `input_param`.
3. The op is auto-registered on import. To ensure it is registered before tests run, import the module explicitly in the test file (e.g. `from textalchemy.pipeline import render as _render_op  # noqa: F401`) — otherwise `all_operations()` may not see it if pytest collects only the test file.
4. Add tests under `tests/test_pipeline/`. If the test uses `isolated()` or `reset()`, restore the registry afterwards — `isolated()` does this automatically; bare `reset()` does not.

## Adding format support

- Both libraries are external, released dependencies. Do not implement or fix their runtime code in this session, patch installed packages, rebuild a release under its existing version, or copy library implementations into this application.
- If application work needs a library change, prepare version, caller, reproducible input, proposed public contract, diagnostics, cancellation/limits, compatibility and acceptance evidence, then transfer the request to the library owner. Its contract and active TODO live in its own project; [OpenDoc ownership](library-requests/opendoc.md) and [OpenDoc Formats ownership](library-requests/opendoc-formats.md) link there. Application TODO may only track integration and user acceptance.
- Check released public APIs first. There are no native engine exceptions. Never import document engines directly, parse native document XML/ZIP or depend on private backend objects in application source. `contracts/libraries.json` owns only consumer API requirements and compatibility imports. Run `uv run python -m tools.check_library_contracts`; CI rejects static/dynamic engine imports, OOXML structure, implementation copies and missing public APIs. Generic task archives and bundled documentation ZIPs are application responsibilities.
- Native PDF page access, managed office-to-PDF conversion and transactional DOCX package editing belong to OpenDoc Formats. TextAlchemy owns template expression/schema policy, revisions, selected edits, task cache and OCR/visual interpretation of returned PNG bytes and document snapshots. Never move these application policies into a format library.
- Install a checked library wheel, update the exact version, bundled wheel/provenance and lockfile, then test integration. Never modify installed library code manually.
- TextAlchemy owns CLI/Web operations, route selection, tasks, OCR orchestration and user quality policies. Pipeline operation adapters keep their keyword-only contract.
- Rich importers return OpenDoc DocumentModel; library import/export registries handle diagnostics, optional engines, validation and cancellation boundaries.
- Compatibility imports use the same module objects; preserve application package paths to avoid loading library code twice under application names.

## Gotchas

- OpenDoc Formats ships the `pptx_to_html` CSS/JS and Pandoc Lua assets. Application facades resolve the installed library; do not restore asset copies in TextAlchemy.
- `argparse` with no subcommand returns `1` and prints help; tests assert this.
- `match` and `stats` default to `./literature_files` and `./renamed` and may pick up a bibliography file from CWD if `-b` is omitted — pass explicit paths in CI.
- `textalchemy.convert` stays importable without python-pptx: the `pptx_to_html` package (python-pptx + Pillow) is resolved lazily via `__getattr__` in `convert/__init__.py`, and `html_writer._preset_geometry()` lazy-imports `_pptx_lib`. `formats/pptx.py` guards `lxml` with try/except (python-pptx pulls it transitively); `extract/latex.py` lazy-imports python-docx.
- OCR optional dependencies (`[project.optional-dependencies] ocr`) include `pytesseract`, `easyocr`, `paddleocr`, `paddlepaddle`. Install full with `uv sync --all-extras`. PaddleOCR requires torch/PaddlePaddle (heavy); `paddlepaddle` is marker-gated off on Python 3.14 (no wheels yet).
- `MANIFEST.in` is required for sdist builds: the package ships non-Python assets under `src/textalchemy/**/{assets,templates,static,lua-filters}/`.
- No typecheck or pre-commit is wired into local commands beyond `ruff`; pre-commit is configured (`.pre-commit-config.yaml`) but optional.
- On Windows, `__main__.py` reconfigures stdout/stderr to UTF-8 (so `→` in op descriptions doesn't blow up `charmap`). Don't remove this.
- `pipeline/__init__.py` owns `register_builtin_operations()`: it imports built-in modules and restores decorated operation specs idempotently. Package import currently calls it as well; CLI/Web entry points call it explicitly. Registration is not owned by eager module imports in `runner.py`. Tests should still use `isolated()` when changing the registry.
- Operation params containing `{...}` are passed through `str.format(**ctx)`. If you have literal `{` in a value, escape as `{{`.
- The registry is a module-global dict; `reset()` clears everything including the auto-imported `pipeline.*` ops. Use `isolated()` in tests, not `reset()`.
