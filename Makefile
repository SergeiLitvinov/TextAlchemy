.PHONY: install test lint format clean

install:
	uv sync --all-extras

test:
	uv run pytest tests/ -v --tb=short

coverage:
	uv run pytest tests/ --cov=textalchemy --cov-report=term-missing

lint:
	uv run ruff check

format:
	uv run ruff check --fix
	uv run ruff format

clean:
	rm -rf .pytest_cache .coverage coverage.xml
	rm -rf src/**/__pycache__ tests/**/__pycache__
	rm -rf *.egg-info

web:
	uv run textalchemy web

.PHONY: docs docs-check docs-generate docs-serve
docs:
	uv run python -m tools.docs build

docs-check:
	uv run python -m tools.docs check

docs-generate:
	uv run python -m tools.docs generate

docs-serve:
	uv run python -m tools.docs serve
