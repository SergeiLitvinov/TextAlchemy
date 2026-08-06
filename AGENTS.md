# AGENTS.md

TextAlchemy — Python toolkit for scientific/educational document processing. Single Python package, single CLI entry point.

## Layout

- `src/textalchemy/__main__.py` — CLI entry: `_setup_parser()` + `main()` dispatch (`argparse` + `match`). Handlers live in `src/textalchemy/cli/` (15 modules: `bibliography_cmd.py`, `bibtex_cmd.py`, `completion_cmd.py`, `convert_cmd.py`, `convert_file_cmd.py`, `extract_cmd.py`, `generate_cmd.py`, `init_cmd.py`, `inspect_cmd.py`, `match_cmd.py`, `plan_cmd.py`, `recognize_cmd.py`, `run_cmd.py`, `template_cmd.py`, `web_cmd.py`).
- `src/textalchemy/core/` — base types (`Document`, `Text`, `Match`, `Signal`, `BibItem`) and the operation registry (`@operation`).
  - `document_model.py` — rich intermediate model (`DocumentModel`, sections/paragraphs/tables/images/formulas, typed `*Properties`), `conversion_graph.py` — capability model + route planner, `document_codec.py` — versioned JSON serialization, `document_adapters.py`, `properties.py`, `diagnostics.py` (`ConversionReport`), `inspection.py` (structure/quality report for `textalchemy inspect`), `database.py`, `io.py`, `hashing.py`, `latex.py`, `config.py`, `exceptions.py`.
- `src/textalchemy/formats/` — atomic format readers: `pdf` (chain `pdfplumber → pypdf → pymupdf`), `docx` (split into `docx_text/style/table/section/drawing/notes` + `docx.py` facade), `pptx` (`pptx.py` — `read_pptx` flat text + `read_pptx_model` DocumentModel importer: slides→sections, shapes→blocks with EMU→pt geometry, groups/transforms, runs/styles/hyperlinks, OMML formulas, images, tables, charts, notes, background; placeholder geometry/styles inherited slide → layout → master via `p:txStyles`; shape metadata in `properties["pptx"]["shape"]`), `txt`/`djvu`, `epub`.
  - PDF geometry/semantics: `pdf_geometry.py` (reading order, blocks, tables, images), `pdf_layout.py`, `pdf_classify.py`, `pdf_images.py` (raster + vector extraction), `pdf_ocr_merge.py` (text layer + OCR fusion), `pdf_ocr_types.py`, `pdf_semantic.py`, `pdf_ocr_merge.py`.
- `src/textalchemy/ooxml/` — shared OPC `PackageGraph` and relationship handling for DOCX/PPTX round-trips.
- `src/textalchemy/pipeline/` — pipeline stages as `@operation`s:
  - `ingest.py` — `ingest.file`: path → `Document`.
  - `extract.py` — `extract.text`: `Document` → `Text` (universal reader); `extract.pdf_model`: PDF → `DocumentModel` (geometry, tables, images, vectors, optional OCR merge); `extract.pptx_model`: PPTX → `DocumentModel` (slides, shapes, tables, images, charts, OMML).
  - `emails_op.py` — `extract.emails`, `render.emails.{docx,txt,debug}`.
  - `signals.py` — author/title/year/doi/isbn signals with configurable weights.
  - `match.py` — `match.bibliography`: `Text`+`Document`+`BibItem[]` → `Match`.
  - `match_files.py` — `match.files`: directory + BibItem[] → `Match[]` (batch; copies matched files to `output_dir`).
  - `bibliography.py` — `bibliography.parse` (path → BibItem[]), `bibliography.smart_parse` (text → BibItem[]).
  - `name.py` — `name.from_match`: `Match` → filename.
  - `render.py` — `render.latex`, `render.latex.pandoc`, `render.docx`, `render.docx_model` (DocumentModel → DOCX), `render.bibtex`, `render.gost`, `render.markdown`, `render.json`.
  - `render_html.py` — `render.html.pptx`: `Document` (.pptx) → `ConversionResult` (HTML viewer).
  - `template.py` — `template.render`: fill `DocumentModel` with data (variables, conditions, loops).
  - `runner.py` — YAML/TOML/JSON pipeline runner.
- `src/textalchemy/convert/` — conversion subsystem:
  - `capabilities.py` / `executor.py` — built-in `ConverterCapabilities` + `ConversionExecutor` that plans a route through `DocumentModel` and executes it (no temp file); `protocols.py`, `backends.py`, `base.py` (`BaseConverter`/`ConversionReport`).
  - `pdf_to_docx.py` — PDF → DOCX (`pdf2docx`, `pymupdf`, `libreoffice`, engine fallback).
  - `docx_writer.py` + `docx_*_writer.py` — `DocumentModel` → DOCX; `html_writer.py` — → self-contained HTML; `pdf_writer.py` — → PDF (reportlab); `docx_to_latex.py` — DOCX → LaTeX.
  - `pptx_to_html/` — PPTX → self-contained HTML viewer (MathML via MathJax). Public API: `PptxToHtmlConverter`, `convert` (see `converter.py:84`). Shipped assets in `pptx_to_html/assets/{css,js}/` are copied to output by default.
- `src/textalchemy/recognize/` — OCR subsystem:
  - `ocr.py` — `OcrEngine` поддерживает три бэкенда: Tesseract, EasyOCR, PaddleOCR. Автоопределение доступного. Поддержка `handwriting` (рукописный текст) и `use_gpu`. Методы `recognize_pdf()` и `recognize_pdf_geometry()`/`recognize_with_geometry()` (координаты блоков для OCR-merge с текстовым слоем PDF).
  - `classifier.py` — `DocumentClassifier` по ключевым словам (статья/диссертация/монография и т.д.).
  - `layout.py` — `LayoutAnalyzer` базовый анализ областей на изображении (текст/таблица/колонтитул).
- `src/textalchemy/{extract,organize,generate,quality,web}/` — other subsystems:
  - `extract/` — legacy: docx → text/LaTeX, emails, `fix_encoding.py`.
  - `organize/` — legacy: bibliography parser, matching, GOST, filename, bibtex.
  - `generate/` — template engine: `template.py` (DSL), `template_schema.py` (data schema), `model_template.py` (DocumentModel-driven DOCX/HTML/PDF generation).
  - `quality/` — visual metrics and perceptual regression.
  - `web/` — FastAPI app (`app.py`), route handlers in `web/routes/` (pages, bibliography, convert, extract, generate, matching, pipeline, recognize), Jinja2 templates + static assets.
- `tests/` — pytest. Subpackages mirror the source: `test_core/`, `test_formats/`, `test_pipeline/`, `test_convert/`, `test_generate/`, `test_organize/`, `test_recognize/`, `test_extract/`, `test_quality/`. Flat: `test_cli.py`, `test_web.py`, `test_database.py`, `test_ooxml_package.py`, `test_template_cli.py`.
- `tests/corpus/` — reproducible scientific DOCX/PDF/PPTX corpus and structural golden data.

## Commands

Always run via `uv` so the lockfile-resolved env is used.

- Install (full): `uv sync --all-extras`
- Minimal install: `uv sync` (core: yaml, platformdirs, pypdf, jinja2, tqdm). Heavy deps live in extras — `pdf` (pymupdf, pdf2docx), `docx` (python-docx), `pptx` (python-pptx, lxml, Pillow), `epub` (ebooklib, bs4), `web` (fastapi, uvicorn, python-multipart, sqlalchemy), `ocr` (pytesseract, easyocr, paddleocr, paddlepaddle). Readers/converters lazy-import their backends and never force them at `import textalchemy`.
- Lint: `uv run ruff check` (config: line-length 130, rules E/F/I/N/W, `pyproject.toml`)
- Format: `uv run ruff check --fix && uv run ruff format`
- Test: `uv run pytest tests/ -v --tb=short` (or `--cov=textalchemy` for coverage). Coverage threshold `--cov-fail-under=80` is enforced whenever `--cov` is active (see `pyproject.toml`).
- Single test: `uv run pytest tests/test_pipeline/test_runner.py::test_run_chained_ingest_extract -v`
- Pipeline run: `uv run textalchemy run pipeline.yaml` (or `textalchemy run --list`, `--json` for JSON output)
- Most commands support `--json` for structured machine-readable output (`extract`, `convert`, `convert-file`, `plan`, `inspect`, `template-check`, `pptx2html`, `gost`, `stats`, `generate`, `bibtex`, `recognize`, `match`, `run`)
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
- `textalchemy.convert` stays importable without python-pptx: the `pptx_to_html` package (python-pptx + Pillow) is resolved lazily via `__getattr__` in `convert/__init__.py`, and `html_writer._preset_geometry()` lazy-imports `_pptx_lib`. `formats/pptx.py` guards `lxml` with try/except (python-pptx pulls it transitively); `extract/latex.py` lazy-imports python-docx.
- OCR optional dependencies (`[project.optional-dependencies] ocr`) include `pytesseract`, `easyocr`, `paddleocr`, `paddlepaddle`. Install full with `uv sync --all-extras`. PaddleOCR requires torch/PaddlePaddle (heavy); `paddlepaddle` is marker-gated off on Python 3.14 (no wheels yet).
- `MANIFEST.in` is required for sdist builds: the package ships non-Python assets under `src/textalchemy/**/{assets,templates,static,lua-filters}/`.
- No typecheck or pre-commit is wired into local commands beyond `ruff`; pre-commit is configured (`.pre-commit-config.yaml`) but optional.
- On Windows, `__main__.py` reconfigures stdout/stderr to UTF-8 (so `→` in op descriptions doesn't blow up `charmap`). Don't remove this.
- `pipeline/runner.py` eagerly imports the other pipeline modules at top to ensure `@operation` decorators fire on first use. If a test imports only `runner`, the other ops still get registered — but the import has a side effect: pytest's test discovery may load `tests/conftest.py` between this and the test, which is fine.
- Operation params containing `{...}` are passed through `str.format(**ctx)`. If you have literal `{` in a value, escape as `{{`.
- The registry is a module-global dict; `reset()` clears everything including the auto-imported `pipeline.*` ops. Use `isolated()` in tests, not `reset()`.
