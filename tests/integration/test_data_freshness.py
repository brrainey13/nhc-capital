"""Integration tests for data freshness and health checks."""

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

FRESHNESS_DAYS = 7  # Data should be no older than this

KEY_TABLES = {
    "saves_odds": {"date_col": "scrape_time", "min_rows": 100},
    "player_odds": {"date_col": "scrape_time", "min_rows": 100},
}


@pytest.fixture
def nhl_db():
    try:
        from lib.db import query
        query("SELECT 1", db="nhl_betting")
        return True
    except Exception:
        pytest.skip("nhl_betting DB not available")


class TestDataFreshness:
    @pytest.mark.parametrize("table,config", KEY_TABLES.items())
    def test_recent_data_exists(self, nhl_db, table, config):
        from lib.db import query_one
        date_col = config["date_col"]
        cutoff = datetime.now(timezone.utc) - timedelta(days=FRESHNESS_DAYS)
        result = query_one(
            f"SELECT COUNT(*) AS cnt FROM {table} WHERE {date_col} > %s",
            [cutoff], db="nhl_betting",
        )
        assert result and result["cnt"] > 0, (
            f"No data in {table} from last {FRESHNESS_DAYS} days"
        )


class TestRowCounts:
    @pytest.mark.parametrize("table,config", KEY_TABLES.items())
    def test_minimum_rows(self, nhl_db, table, config):
        from lib.db import query_one
        result = query_one(f"SELECT COUNT(*) AS cnt FROM {table}", db="nhl_betting")
        assert result["cnt"] >= config["min_rows"], (
            f"{table} has {result['cnt']} rows, expected >= {config['min_rows']}"
        )


class TestNullChecks:
    def test_saves_odds_no_null_keys(self, nhl_db):
        from lib.db import query_one
        result = query_one(
            "SELECT COUNT(*) AS cnt FROM saves_odds WHERE scrape_time IS NULL",
            db="nhl_betting",
        )
        assert result["cnt"] == 0, "saves_odds has null scrape_time values"
