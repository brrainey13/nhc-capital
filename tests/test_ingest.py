"""Tests for lib/ingest.py — data ingestion helpers."""

from unittest.mock import MagicMock, patch

import pytest


class TestValidateSchema:
    @patch("lib.ingest.get_table_columns")
    def test_valid_schema(self, mock_cols):
        mock_cols.return_value = ["name", "team", "goals"]
        from lib.ingest import validate_schema
        result = validate_schema("test", [{"name": "A", "team": "B", "goals": 1}])
        assert result["valid"] is True

    @patch("lib.ingest.get_table_columns")
    def test_extra_columns(self, mock_cols):
        mock_cols.return_value = ["name", "team"]
        from lib.ingest import validate_schema
        result = validate_schema("test", [{"name": "A", "team": "B", "extra": 1}])
        assert result["valid"] is False
        assert "extra" in result["extra_cols"]

    @patch("lib.ingest.get_table_columns")
    def test_missing_table(self, mock_cols):
        mock_cols.return_value = []
        from lib.ingest import validate_schema
        result = validate_schema("nonexistent", [{"a": 1}])
        assert result["valid"] is False

    def test_empty_rows(self):
        from lib.ingest import validate_schema
        result = validate_schema("test", [])
        assert result["valid"] is True


class TestIngestRows:
    @patch("lib.ingest.log_ingestion")
    @patch("lib.ingest.psycopg2")
    @patch("lib.ingest.get_etl_connection")
    @patch("lib.ingest.validate_schema")
    def test_ingest_success(self, mock_validate, mock_conn_ctx, mock_pg, mock_log):
        mock_validate.return_value = {"valid": True, "errors": []}
        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn_ctx.return_value = mock_conn

        from lib.ingest import ingest_rows
        count = ingest_rows("test", [{"a": 1}, {"a": 2}], validate=True)
        assert count == 2

    @patch("lib.ingest.log_ingestion")
    @patch("lib.ingest.validate_schema")
    def test_ingest_validation_failure(self, mock_validate, mock_log):
        mock_validate.return_value = {"valid": False, "errors": ["bad columns"]}
        from lib.ingest import ingest_rows
        with pytest.raises(ValueError, match="Schema validation failed"):
            ingest_rows("test", [{"bad": 1}])

    def test_ingest_empty(self):
        from lib.ingest import ingest_rows
        assert ingest_rows("test", []) == 0


class TestIngestDf:
    @patch("lib.ingest.ingest_rows")
    def test_ingest_df_calls_ingest_rows(self, mock_ingest):
        import pandas as pd
        mock_ingest.return_value = 3
        from lib.ingest import ingest_df
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = ingest_df("test", df)
        assert result == 3
        mock_ingest.assert_called_once()
