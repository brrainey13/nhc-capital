import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("ALLOWED_EMAILS", "test@example.com")

# Add backend to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
import db
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from main import app
from routes import usage


@pytest_asyncio.fixture(autouse=True)
async def setup_pool():
    host = db.DB_HOST
    nhl_pool = await asyncpg.create_pool(
        f"postgresql://{os.environ.get('PGUSER', 'nhc_agent')}@{host}:5432/nhl_betting",
        min_size=1, max_size=3,
    )
    db.default_pool = nhl_pool
    # Mutate the existing dict (don't replace — routes hold a reference)
    db.pools.clear()
    db.pools["nhl_betting"] = nhl_pool
    try:
        poly_pool = await asyncpg.create_pool(
            f"postgresql://{os.environ.get('PGUSER', 'nhc_agent')}@{host}:5432/polymarket",
            min_size=1, max_size=2,
        )
        db.pools["polymarket"] = poly_pool
    except Exception:
        pass
    try:
        cc_pool = await asyncpg.create_pool(
            f"postgresql://{os.environ.get('PGUSER', 'nhc_agent')}@{host}:5432/cook_county",
            min_size=1, max_size=2,
        )
        db.pools["cook_county"] = cc_pool
    except Exception:
        pass
    await db._discover_tables()
    yield
    for p in db.pools.values():
        await p.close()
    db.pools.clear()


@pytest_asyncio.fixture
async def client():
    """Authenticated client (simulates Cloudflare Access OAuth user)."""
    transport = ASGITransport(app=app)
    headers = {"cf-access-authenticated-user-email": "test@example.com"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        yield ac


@pytest_asyncio.fixture
async def anon_client():
    """Unauthenticated client (no auth headers)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# 0. Auth tests
@pytest.mark.asyncio
async def test_health_no_auth(anon_client):
    r = await anon_client.get("/api/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_api_requires_auth(anon_client):
    r = await anon_client.get("/api/tables")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_rejects_wrong_email(anon_client):
    r = await anon_client.get("/api/tables", headers={"cf-access-authenticated-user-email": "hacker@evil.com"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_api_accepts_valid_email(client):
    r = await client.get("/api/tables")
    assert r.status_code == 200


# 1. Health check
@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# 2. List tables
@pytest.mark.asyncio
async def test_list_tables(client):
    r = await client.get("/api/tables")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    names = [t["name"] for t in data]
    assert "teams" in names


# 3. Table schema
@pytest.mark.asyncio
async def test_table_schema(client):
    r = await client.get("/api/tables/teams/schema")
    assert r.status_code == 200
    assert r.json()["table"] == "teams"
    assert len(r.json()["columns"]) > 0


# 4. Table schema 404
@pytest.mark.asyncio
async def test_table_schema_not_found(client):
    r = await client.get("/api/tables/nonexistent/schema")
    assert r.status_code == 404


# 5. Table data
@pytest.mark.asyncio
async def test_table_data(client):
    r = await client.get("/api/tables/teams/data?limit=5&offset=0")
    assert r.status_code == 200
    d = r.json()
    assert "rows" in d
    assert "total" in d
    assert d["limit"] == 5


# 6. Pagination
@pytest.mark.asyncio
async def test_pagination(client):
    r1 = await client.get("/api/tables/teams/data?limit=2&offset=0")
    r2 = await client.get("/api/tables/teams/data?limit=2&offset=2")
    assert r1.status_code == 200
    assert r2.status_code == 200
    rows1 = r1.json()["rows"]
    rows2 = r2.json()["rows"]
    if rows1 and rows2:
        assert rows1 != rows2


# 7. Read-only query
@pytest.mark.asyncio
async def test_query_select(client):
    r = await client.post("/api/query", json={"sql": "SELECT 1 AS val"})
    assert r.status_code == 200
    assert r.json()["rows"][0]["val"] == 1


# 8-12. Reject dangerous SQL
@pytest.mark.asyncio
async def test_reject_insert(client):
    r = await client.post("/api/query", json={"sql": "INSERT INTO teams VALUES (1)"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reject_drop(client):
    r = await client.post("/api/query", json={"sql": "DROP TABLE teams"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reject_delete(client):
    r = await client.post("/api/query", json={"sql": "DELETE FROM teams"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reject_update(client):
    r = await client.post("/api/query", json={"sql": "UPDATE teams SET id=1"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reject_truncate(client):
    r = await client.post("/api/query", json={"sql": "TRUNCATE teams"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reject_set_command(client):
    r = await client.post("/api/query", json={"sql": "SET work_mem='4MB'"})
    assert r.status_code == 403


# 14. Empty query
@pytest.mark.asyncio
async def test_empty_query(client):
    r = await client.post("/api/query", json={"sql": ""})
    assert r.status_code == 400


# 15. Invalid SQL
@pytest.mark.asyncio
async def test_invalid_sql(client):
    r = await client.post("/api/query", json={"sql": "SELEC FROM"})
    assert r.status_code == 403


# 16. Table data 404
@pytest.mark.asyncio
async def test_table_data_not_found(client):
    r = await client.get("/api/tables/fake_table/data")
    assert r.status_code == 404


# 17. Usage endpoint
@pytest.mark.asyncio
async def test_usage(client):
    r = await client.get("/api/usage")
    assert r.status_code == 200
    data = r.json()
    assert "sessions" in data
    assert "totals" in data
    assert "models" in data
    assert "claude_rate_limit" in data
    assert "windows" in data
    assert "trend" in data
    assert "freshness" in data


@pytest.mark.asyncio
async def test_nhl_bankroll(client):
    r = await client.get("/api/nhl/bankroll")
    assert r.status_code == 200
    data = r.json()
    assert "current_balance" in data
    assert "transactions" in data
    assert isinstance(data["transactions"], list)


@pytest.mark.asyncio
async def test_nhl_bankroll_summary(client):
    r = await client.get("/api/nhl/bankroll/summary")
    assert r.status_code == 200
    data = r.json()
    assert "current_balance" in data
    assert "balance_chart" in data
    assert "daily_pl" in data
    assert "win_rate" in data
    assert "roi" in data


@pytest.mark.asyncio
async def test_usage_metrics_from_fixture(client, tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    recent_ms = int((now - timedelta(minutes=30)).timestamp() * 1000)
    day_old_ms = int((now - timedelta(hours=20)).timestamp() * 1000)

    sample = {
        "a": {
            "displayName": "discord:1#admin-dashboard",
            "totalTokens": 1000, "inputTokens": 700, "outputTokens": 300,
            "contextTokens": 128000, "updatedAt": recent_ms, "model": "gpt-test",
        },
        "b": {
            "displayName": "discord:1#nhl-betting",
            "totalTokens": 500, "inputTokens": 250, "outputTokens": 250,
            "contextTokens": 128000, "updatedAt": day_old_ms, "model": "gpt-test",
        },
        "c": {
            "displayName": "discord:1#general",
            "totalTokens": 2000, "inputTokens": 1200, "outputTokens": 800,
            "contextTokens": 200000, "updatedAt": recent_ms,
            "model": "claude-opus-4-6", "modelProvider": "anthropic",
            "rateLimit": {"resetAt": (now + timedelta(minutes=20)).isoformat()},
        },
    }

    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps(sample))
    monkeypatch.setattr(usage, "SESSIONS_FILE", sessions_file)

    r = await client.get("/api/usage")
    assert r.status_code == 200
    data = r.json()

    assert data["totals"]["total_tokens"] == 3500
    assert data["totals"]["session_count"] == 3
    assert data["windows"]["last_1h"]["session_count"] == 2
    assert data["windows"]["last_1h"]["total_tokens"] == 3000
    assert data["windows"]["last_24h"]["session_count"] == 3
    assert data["top_consumers"][0]["label"] == "#general"
    assert len(data["trend"]["buckets"]) == 12
    assert data["models"][0]["model"] == "claude-opus-4-6"
    assert data["models"][0]["total_tokens"] == 2000
    assert data["claude_rate_limit"]["status"] == "limited"
    assert data["claude_rate_limit"]["reset_at"] is not None


@pytest.mark.asyncio
async def test_usage_claude_rate_limit_unknown_without_reset(client, tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    sample = {
        "c": {
            "displayName": "discord:1#general",
            "totalTokens": 500, "inputTokens": 250, "outputTokens": 250,
            "contextTokens": 200000, "updatedAt": int(now.timestamp() * 1000),
            "model": "claude-opus-4-6", "modelProvider": "anthropic",
        }
    }

    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps(sample))
    monkeypatch.setattr(usage, "SESSIONS_FILE", sessions_file)

    r = await client.get("/api/usage")
    assert r.status_code == 200
    data = r.json()
    assert data["claude_rate_limit"]["status"] == "unknown"
    assert data["claude_rate_limit"]["reset_at"] is None


# 18. Sorting
@pytest.mark.asyncio
async def test_table_data_sort(client):
    r = await client.get("/api/tables/teams/data?limit=5&sort_by=team_name&sort_dir=asc")
    assert r.status_code == 200
    names = [row["team_name"] for row in r.json()["rows"]]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_table_data_sort_invalid_column(client):
    r = await client.get("/api/tables/teams/data?limit=5&sort_by=DROP+TABLE+teams")
    assert r.status_code == 400


# 20. Filtering
@pytest.mark.asyncio
async def test_table_data_filter(client):
    filters = json.dumps({"conference_name": "Eastern"})
    r = await client.get(f"/api/tables/teams/data?limit=100&filters={filters}")
    assert r.status_code == 200
    d = r.json()
    for row in d["rows"]:
        assert "Eastern" in str(row["conference_name"])
    assert d["filtered_total"] <= d["total"]


@pytest.mark.asyncio
async def test_table_data_filter_invalid_column(client):
    filters = json.dumps({"nonexistent_col": "value"})
    r = await client.get(f"/api/tables/teams/data?limit=5&filters={filters}")
    assert r.status_code == 400


# 22. Grouped
@pytest.mark.asyncio
async def test_grouped(client):
    r = await client.get("/api/tables/teams/grouped?group_by=conference_name")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "value" in data[0]
    assert "count" in data[0]


@pytest.mark.asyncio
async def test_grouped_invalid_column(client):
    r = await client.get("/api/tables/teams/grouped?group_by=DROP+TABLE+teams")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_grouped_invalid_table(client):
    r = await client.get("/api/tables/fake_table/grouped?group_by=id")
    assert r.status_code == 404


# 25. Schema data types
@pytest.mark.asyncio
async def test_schema_has_data_types(client):
    r = await client.get("/api/tables/teams/schema")
    assert r.status_code == 200
    types = {c["column_name"]: c["data_type"] for c in r.json()["columns"]}
    assert types["team_id"] == "integer"
    assert types["team_name"] == "text"


# 26. Sort descending
@pytest.mark.asyncio
async def test_table_data_sort_desc(client):
    r = await client.get("/api/tables/teams/data?limit=5&sort_by=team_name&sort_dir=desc")
    assert r.status_code == 200
    names = [row["team_name"] for row in r.json()["rows"]]
    assert names == sorted(names, reverse=True)


# 27. Numeric range filter
@pytest.mark.asyncio
async def test_numeric_range_filter(client):
    filters = json.dumps({"team_id": {"min": 1, "max": 10}})
    r = await client.get(f"/api/tables/teams/data?limit=100&filters={filters}")
    assert r.status_code == 200
    for row in r.json()["rows"]:
        assert 1 <= row["team_id"] <= 10


# NL query removed — repurposed free tokens for LLM code review agent
