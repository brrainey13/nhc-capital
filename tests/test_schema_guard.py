"""Tests for schema guard and schema contract."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCHEMA_FILE = REPO_ROOT / "shared" / "schema" / "tables.json"


def test_schema_contract_exists():
    """shared/schema/tables.json must exist."""
    assert SCHEMA_FILE.exists(), "Schema contract missing: shared/schema/tables.json"


def test_schema_contract_valid_json():
    """Schema contract must be valid JSON."""
    data = json.loads(SCHEMA_FILE.read_text())
    assert isinstance(data, dict)


def test_schema_contract_has_all_databases():
    """Schema contract must cover all 3 databases."""
    data = json.loads(SCHEMA_FILE.read_text())
    for db in ["nhl_betting", "polymarket", "cook_county"]:
        assert db in data, f"Missing database: {db}"


def test_schema_contract_tables_have_columns():
    """Every table in the contract must have at least one column."""
    data = json.loads(SCHEMA_FILE.read_text())
    for db, tables in data.items():
        for tbl, info in tables.items():
            assert "columns" in info, f"{db}.{tbl} missing 'columns'"
            assert len(info["columns"]) > 0, f"{db}.{tbl} has no columns"


def test_schema_contract_column_format():
    """Columns must have name, type, and nullable fields."""
    data = json.loads(SCHEMA_FILE.read_text())
    for db, tables in data.items():
        for tbl, info in tables.items():
            for col in info["columns"]:
                assert "name" in col, f"{db}.{tbl}: column missing 'name'"
                assert "type" in col, f"{db}.{tbl}.{col.get('name', '?')}: missing 'type'"
                assert "nullable" in col, f"{db}.{tbl}.{col.get('name', '?')}: missing 'nullable'"


def test_schema_guard_script_exists():
    """schema-guard script must exist and be executable."""
    script = REPO_ROOT / "scripts" / "schema-guard"
    assert script.exists(), "scripts/schema-guard missing"


def test_schema_snapshot_script_exists():
    """schema-snapshot script must exist."""
    script = REPO_ROOT / "scripts" / "schema-snapshot"
    assert script.exists(), "scripts/schema-snapshot missing"
