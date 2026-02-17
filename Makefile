.PHONY: test lint docs-guard test-nhl test-real-estate test-polymarket test-admin setup setup-venvs

# Per-project Python paths (use these when running code)
NHL_PYTHON = nhl-betting/.venv/bin/python
POLY_PYTHON = polymarket/.venv/bin/python
RE_PYTHON = real-estate/.venv/bin/python
ADMIN_PYTHON = admin-dashboard/.venv/bin/python

setup-venvs:
	cd nhl-betting && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
	cd polymarket && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
	cd real-estate && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
	cd admin-dashboard && python3 -m venv .venv && .venv/bin/pip install -q -r backend/requirements.txt

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
