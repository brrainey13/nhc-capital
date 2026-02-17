.PHONY: test lint docs-guard test-nhl test-real-estate test-polymarket test-admin setup

setup:
	python3 -m pip install pytest ruff psycopg2-binary requests --break-system-packages

test:
	pytest

lint:
	ruff check .

test-nhl:
	pytest nhl-betting/ -v

test-real-estate:
	pytest real-estate/ -v

test-polymarket:
	pytest polymarket/ -v

test-admin:
	pytest admin-dashboard/ -v

docs-guard:
	python3 scripts/docs-guard

ci: lint docs-guard test
	@echo "All checks passed."
