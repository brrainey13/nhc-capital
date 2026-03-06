"""Regression tests for dashboard API endpoints."""

from unittest.mock import AsyncMock, patch

from routes import nhl_bankroll, tables


def _tables_patches():
    pool = AsyncMock()
    pool.fetchval.return_value = 34
    return (
        patch.object(tables, "ALLOWED_TABLES", {"teams", "games"}),
        patch.object(tables, "TABLE_DB_MAP", {"teams": "nhl_betting", "games": "nhl_betting"}),
        patch.object(tables, "pools", {"nhl_betting": pool}),
    )


def _bankroll_pool(*, history_only=False):
    pool = AsyncMock()
    if history_only:
        pool.fetch.return_value = [
            {"event_date": "2026-03-05", "balance": 1200.0},
            {"event_date": "2026-03-06", "balance": 1265.5},
        ]
        return pool

    pool.fetchrow.side_effect = [
        {"balance": 1265.5},
        {"wins": 7, "losses": 3, "graded_bets": 10, "total_pl": 65.5, "total_staked": 500.0},
    ]
    pool.fetch.return_value = [
        {"event_date": "2026-03-05", "daily_pl": 25.0, "balance": 1200.0},
        {"event_date": "2026-03-06", "daily_pl": 40.5, "balance": 1265.5},
    ]
    return pool


class TestApiEndpoints:
    def test_api_health_returns_ok(self, fastapi_client):
        with fastapi_client(base_url="http://dashboard.test") as client:
            response = client.get("/api/health")

        assert response.status_code == 200, "The API health endpoint should be public and healthy."
        assert response.json() == {"status": "ok"}, "Health payload should stay stable for monitors."

    def test_tables_returns_list_of_tables(self, fastapi_client):
        allowed_tables, table_map, pools = _tables_patches()
        with allowed_tables, table_map, pools, fastapi_client(
            base_url="http://dashboard.test",
            headers={"x-api-key": "super-secret-test-key"},
        ) as client:
            response = client.get("/api/tables")

        data = response.json()
        assert response.status_code == 200, "Authenticated callers should be able to list tables."
        assert isinstance(data, list), "The tables endpoint should return a JSON array."
        assert {row["name"] for row in data} == {"games", "teams"}, "The response should include discovered tables."

    def test_bankroll_summary_returns_expected_shape(self, fastapi_client):
        pool = _bankroll_pool()
        with patch.object(nhl_bankroll, "get_pool", return_value=pool), fastapi_client(
            base_url="http://dashboard.test",
            headers={"x-api-key": "super-secret-test-key"},
        ) as client:
            response = client.get("/api/nhl/bankroll/summary")

        data = response.json()
        assert response.status_code == 200, "Authenticated callers should receive bankroll summary data."
        assert {"current_balance", "daily_pl", "balance_chart", "wins", "roi"} <= data.keys(), (
            "The bankroll summary payload should expose the dashboard fields the frontend depends on."
        )
        assert isinstance(data["daily_pl"], list), "Daily P/L should be returned as an array."

    def test_bankroll_history_returns_array(self, fastapi_client):
        pool = _bankroll_pool(history_only=True)
        with patch.object(nhl_bankroll, "get_pool", return_value=pool), fastapi_client(
            base_url="http://dashboard.test",
            headers={"x-api-key": "super-secret-test-key"},
        ) as client:
            response = client.get("/api/nhl/bankroll/history")

        data = response.json()
        assert response.status_code == 200, "Authenticated callers should receive bankroll history data."
        assert isinstance(data, list), "The bankroll history endpoint should return an array."
        assert data[0]["date"] == "2026-03-05", "History rows should preserve event dates."

    def test_protected_endpoints_require_auth(self, fastapi_client):
        with fastapi_client(base_url="http://dashboard.test") as client:
            tables_response = client.get("/api/tables")
            summary_response = client.get("/api/nhl/bankroll/summary")
            history_response = client.get("/api/nhl/bankroll/history")

        assert tables_response.status_code == 403, "Anonymous callers should not access /api/tables."
        assert summary_response.status_code == 403, "Anonymous callers should not access bankroll summary."
        assert history_response.status_code == 403, "Anonymous callers should not access bankroll history."
