.PHONY: check fix freeze init-dev test test-integration


init-dev:
	pip install -r dev.txt -r requirements.txt

check:
	@echo "Running check..."
	ruff format --check src tests
	ruff check src tests
	pyright

fix:
	@echo "Running fix..."
	ruff format src tests
	ruff check --fix src tests

test:
	PYTHONPATH=src python -m unittest tests.test_unit -v

test-integration:
	PYTHONPATH=src python -m unittest tests.test_integration -v

freeze:
	@echo "Freezing dependencies..."
	uv lock
	uv export --no-install-project --no-hashes --no-dev --format requirements-txt -o requirements.txt
	uv export --no-install-project --no-hashes --group dev --format requirements-txt -o dev.txt

# Default target
.DEFAULT_GOAL := check
