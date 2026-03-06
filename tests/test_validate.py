"""Tests for lib/validate.py — data validation helpers."""



class TestValidateNotNull:
    def test_all_valid(self, sample_df):
        from lib.validate import validate_not_null
        result = validate_not_null(sample_df, ["player_name", "team"])
        assert result["valid"] is True

    def test_has_nulls(self, sample_df_with_nulls):
        from lib.validate import validate_not_null
        result = validate_not_null(sample_df_with_nulls, ["player_name", "team"])
        assert result["valid"] is False
        assert len(result["errors"]) == 2

    def test_missing_column(self, sample_df):
        from lib.validate import validate_not_null
        result = validate_not_null(sample_df, ["nonexistent"])
        assert result["valid"] is False
        assert "not found" in result["errors"][0]


class TestValidateUnique:
    def test_unique(self, sample_df):
        from lib.validate import validate_unique
        result = validate_unique(sample_df, ["player_name"])
        assert result["valid"] is True

    def test_duplicates(self, sample_df_with_dupes):
        from lib.validate import validate_unique
        result = validate_unique(sample_df_with_dupes, ["player_name", "team"])
        assert result["valid"] is False
        assert result["details"]["duplicate_count"] == 2

    def test_missing_column(self, sample_df):
        from lib.validate import validate_unique
        result = validate_unique(sample_df, ["nonexistent"])
        assert result["valid"] is False


class TestValidateRange:
    def test_in_range(self, sample_df):
        from lib.validate import validate_range
        result = validate_range(sample_df, "goals", min_val=0, max_val=10)
        assert result["valid"] is True

    def test_below_min(self, sample_df):
        from lib.validate import validate_range
        result = validate_range(sample_df, "goals", min_val=4)
        assert result["valid"] is False
        assert result["details"]["below_min"] == 1

    def test_above_max(self, sample_df):
        from lib.validate import validate_range
        result = validate_range(sample_df, "goals", max_val=3)
        assert result["valid"] is False
        assert result["details"]["above_max"] == 2

    def test_missing_column(self, sample_df):
        from lib.validate import validate_range
        result = validate_range(sample_df, "nonexistent", min_val=0)
        assert result["valid"] is False


class TestValidateSchemaMatch:
    def test_match(self, sample_df):
        from unittest.mock import patch
        with patch("lib.ingest.get_table_columns", return_value=["player_name", "team", "goals", "assists"]):
            from lib.validate import validate_schema_match
            result = validate_schema_match(sample_df, "test_table")
            assert result["valid"] is True

    def test_extra_columns(self, sample_df):
        from unittest.mock import patch
        with patch("lib.ingest.get_table_columns", return_value=["player_name", "team"]):
            from lib.validate import validate_schema_match
            result = validate_schema_match(sample_df, "test_table")
            assert result["valid"] is False
            assert "goals" in result["details"]["extra_columns"]
