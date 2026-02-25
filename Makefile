.PHONY: install install-dev test lint format clean security typecheck check

install:
	pip install -r requirements.txt

install-dev: install
	pip install -e ".[dev]"

test:
	python -m pytest tests/ -v --tb=short

lint:
	ruff check nightwire/
	black --check nightwire/

format:
	black nightwire/ tests/
	ruff check --fix nightwire/

typecheck:
	python -m mypy nightwire/ --ignore-missing-imports

security:
	bandit -r nightwire/ -c pyproject.toml || true
	safety check || true

check: lint typecheck test security

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf htmlcov/ .coverage .mypy_cache/ .ruff_cache/ *.egg-info/
