# AGENTS.md

TextAlchemy — Python toolkit for scientific/educational document processing. Single Python package, single CLI entry point.

## Layout

- `src/textalchemy/__main__.py` — CLI entry: `_setup_parser()` + `main()` dispatch (`argparse` + `match`). Handlers live in `src/textalchemy/cli/` (12 modules: `convert_cmd.py`, `extract_cmd.py`, `match_cmd.py`, `bibliography_cmd.py`, `generate_cmd.py`, `recognize_cmd.py`, `bibtex_cmd.py`, `init_cmd.py`, `web_cmd.py`, `run_cmd.py`).
- `src/textalchemy/convert/` — converters; each implements `BaseConverter` from `base.py` and returns `ConversionResult`.
  - `pdf_to_docx.py` — PDF → DOCX (`pdf2docx`, `pymupdf`, `libreoffice`).
  - `pptx_to_html/` — PPTX → self-contained HTML viewer (MathML via MathJax). Public API: `PptxToHtmlConverter`, `convert` (see `converter.py:84`). Shipped assets in `pptx_to_html/assets/{css,js}/` are copied to output by default.
- `src/textalchemy/recognize/` — OCR subsystem:
  - `ocr.py` — `OcrEngine` поддерживает три бэкенда: Tesseract, EasyOCR, PaddleOCR. Автоопределение доступного. Поддержка `handwriting` (рукописный текст) и `use_gpu`. Метод `recognize_pdf()` конвертит PDF → изображения через PyMuPDF с масштабированием.
  - `classifier.py` — `DocumentClassifier` по ключевым словам (статья/диссертация/монография и т.д.).
  - `layout.py` — `LayoutAnalyzer` базовый анализ областей на изображении (текст/таблица/колонтитул).
- `src/textalchemy/{extract,organize,generate,web}/` — other subsystems.
- `src/textalchemy/core/` — base types (`Document`, `Text`, `Match`, `Signal`, `BibItem`) and the operation registry (`@operation`).
- `src/textalchemy/formats/` — atomic format readers: `pdf` (chain `pdfplumber → pypdf → pymupdf`), `docx`, `txt`/`djvu`.
- `src/textalchemy/pipeline/` — pipeline stages as `@operation`s:
  - `ingest.py` — `ingest.file`: path → `Document`.
  - `extract.py` — `extract.text`: `Document` → `Text` (universal reader).
  - `signals.py` — author/title/year/doi/isbn signals with configurable weights.
  - `match.py` — `match.bibliography`: `Text`+`Document`+`BibItem[]` → `Match`.
  - `match_files.py` — `match.files`: directory + BibItem[] → `Match[]` (batch; copies matched files to `output_dir`).
  - `bibliography.py` — `bibliography.parse` (path → BibItem[]), `bibliography.smart_parse` (text → BibItem[]).
  - `name.py` — `name.from_match`: `Match` → filename.
  - `render.py` — `render.latex`, `render.latex.pandoc`, `render.docx`, `render.bibtex`, `render.gost`, `render.markdown`, `render.json`.
  - `render_html.py` — `render.html.pptx`: `Document` (.pptx) → `ConversionResult` (HTML viewer).
  - `runner.py` — YAML/TOML/JSON pipeline runner.
- `tests/` — pytest. Subpackage `tests/pipeline/` and `tests/convert/` mirror the source. Flat: `test_cli.py`, `test_web.py`, `test_database.py`.
- `reference/` — legacy `.doc` and README drafts; not built into the package.

## Commands

Always run via `uv` so the lockfile-resolved env is used.

- Install (full): `uv sync --all-extras`
- Lint: `uv run ruff check` (config: line-length 130, rules E/F/I/N/W, `pyproject.toml`)
- Format: `uv run ruff check --fix && uv run ruff format`
- Test: `uv run pytest tests/ -v --tb=short` (or `--cov=textalchemy` for coverage)
- Single test: `uv run pytest tests/test_pipeline/test_runner.py::test_run_chained_ingest_extract -v`
- Pipeline run: `uv run textalchemy run pipeline.yaml` (or `textalchemy run --list`, `--json` for JSON output)
- Most commands support `--json` for structured machine-readable output (`extract`, `convert`, `pptx2html`, `gost`, `stats`, `generate`, `bibtex`, `recognize`, `match`, `run`)
- Web UI: `uv run textalchemy web` (defaults 127.0.0.1:8000)
- OCR: `uv run textalchemy recognize input.pdf --backend paddle --gpu --mode handwriting --output result.docx`
- CLI entry: `textalchemy = textalchemy.__main__:main` (see `pyproject.toml`)

Equivalent `make` targets exist in the `Makefile` (`make install|test|lint|format|coverage|web`).

## CI

`.github/workflows/ci.yml` runs on Python 3.11/3.12/3.13: `uv sync --all-extras` → `uv run ruff check` → `uv run pytest tests/ --cov=textalchemy --cov-report=xml` (uploads to codecov). Required order: install → lint → test.

## Operation contract (pipeline/)

Every operation is `@operation("id", input_type=..., output_type=..., input_param=..., tags=[...])`. Strict contract:

1. **All parameters are keyword-only** — `def render_latex(*, text: Text, title: str = "Document"): ...`. The runner calls operations with `**kwargs` only, so positional-only parameters will fail.
2. **`input_param` declares the input kwarg name** (default `"input"`). The runner resolves a step's `input: ctx_name` field into `params[input_param]`.
3. **Return values are JSON-serializable OR `Path`/`Document`/`Text`/`Match`/`BibItem`** — anything else breaks `--json` output and `RunResult.to_dict()`.
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

## Adding a new format reader

- Add a function in `src/textalchemy/formats/<format>.py` returning `Text` (or `list[BibItem]` for bib formats). The function should never raise on missing optional dependencies — return a `Text` with `warnings=[...]` instead, so the pipeline can record the issue.
- For PDF-like formats, follow the `pdf.py` pattern: try engines in order and return the first non-empty result.
- Wire into `pipeline/extract.py` (and any new pipeline op).

## Adding a new converter

- Subclass `BaseConverter` and return `ConversionResult` (`src/textalchemy/convert/base.py`).
- Re-export from `src/textalchemy/convert/__init__.py` and add a CLI handler in `__main__.py`.
- If it ships static assets (css/js/templates), add a `recursive-include` line to `MANIFEST.in`.

## Gotchas

- `pptx_to_html` ships with `assets/` (css, js) and uses `Path(__file__).parent / "assets"` at runtime — do not rename the package or move assets without updating both `MANIFEST.in` and `converter.py:_copy_static_assets`.
- `argparse` with no subcommand returns `1` and prints help; tests assert this.
- `match` and `stats` default to `./literature_files` and `./renamed` and may pick up a bibliography file from CWD if `-b` is omitted — pass explicit paths in CI.
- `pyproject.toml` does not declare a `[project.optional-dependencies]` entry for `pptx`; `python-pptx` and `lxml` are in core `dependencies`.
- OCR optional dependencies (`[project.optional-dependencies] ocr`) include `pytesseract`, `easyocr`, `paddleocr`, `paddlepaddle`. Install full with `uv sync --all-extras`. PaddleOCR requires torch/PaddlePaddle (heavy).
- `MANIFEST.in` is required for sdist builds: the package ships non-Python assets under `src/textalchemy/**/{assets,templates,static,lua-filters}/`.
- No typecheck or pre-commit is wired into local commands beyond `ruff`; pre-commit is configured (`.pre-commit-config.yaml`) but optional.
- On Windows, `__main__.py` reconfigures stdout/stderr to UTF-8 (so `→` in op descriptions doesn't blow up `charmap`). Don't remove this.
- `pipeline/runner.py` eagerly imports the other pipeline modules at top to ensure `@operation` decorators fire on first use. If a test imports only `runner`, the other ops still get registered — but the import has a side effect: pytest's test discovery may load `tests/conftest.py` between this and the test, which is fine.
- Operation params containing `{...}` are passed through `str.format(**ctx)`. If you have literal `{` in a value, escape as `{{`.
- The registry is a module-global dict; `reset()` clears everything including the auto-imported `pipeline.*` ops. Use `isolated()` in tests, not `reset()`.
