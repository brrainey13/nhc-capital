import sys
from pathlib import Path

# Add backend to path so we can import main
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from main import app


@pytest_asyncio.fixture(autouse=True)
async def setup_pool():
    import main
    main.pool = await asyncpg.create_pool(
        "postgresql://connorrainey@localhost:5432/nhl_betting",
        min_size=1, max_size=3,
    )
    yield
    await main.pool.close()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


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


# 8. Reject INSERT
@pytest.mark.asyncio
async def test_reject_insert(client):
    r = await client.post("/api/query", json={"sql": "INSERT INTO teams VALUES (1)"})
    assert r.status_code == 403


# 9. Reject DROP
@pytest.mark.asyncio
async def test_reject_drop(client):
    r = await client.post("/api/query", json={"sql": "DROP TABLE teams"})
    assert r.status_code == 403


# 10. Reject DELETE
@pytest.mark.asyncio
async def test_reject_delete(client):
    r = await client.post("/api/query", json={"sql": "DELETE FROM teams"})
    assert r.status_code == 403


# 11. Reject UPDATE
@pytest.mark.asyncio
async def test_reject_update(client):
    r = await client.post("/api/query", json={"sql": "UPDATE teams SET id=1"})
    assert r.status_code == 403


# 12. Reject TRUNCATE
@pytest.mark.asyncio
async def test_reject_truncate(client):
    r = await client.post("/api/query", json={"sql": "TRUNCATE teams"})
    assert r.status_code == 403


# 13. Reject non-read-only command
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
    assert isinstance(data["sessions"], list)
    totals = data["totals"]
    assert "total_tokens" in totals
    assert "input_tokens" in totals
    assert "output_tokens" in totals


# 18. Sorting — sort_by valid column
@pytest.mark.asyncio
async def test_table_data_sort(client):
    r = await client.get("/api/tables/teams/data?limit=5&sort_by=team_name&sort_dir=asc")
    assert r.status_code == 200
    d = r.json()
    names = [row["team_name"] for row in d["rows"]]
    assert names == sorted(names)


# 19. Sorting — invalid column rejected
@pytest.mark.asyncio
async def test_table_data_sort_invalid_column(client):
    r = await client.get("/api/tables/teams/data?limit=5&sort_by=DROP+TABLE+teams")
    assert r.status_code == 400


# 20. Filtering — text filter
@pytest.mark.asyncio
async def test_table_data_filter(client):
    import json as _json

    filters = _json.dumps({"conference_name": "Eastern"})
    r = await client.get(f"/api/tables/teams/data?limit=100&filters={filters}")
    assert r.status_code == 200
    d = r.json()
    for row in d["rows"]:
        assert "Eastern" in str(row["conference_name"])
    assert d["filtered_total"] <= d["total"]


# 21. Filtering — invalid filter column rejected
@pytest.mark.asyncio
async def test_table_data_filter_invalid_column(client):
    import json as _json

    filters = _json.dumps({"nonexistent_col": "value"})
    r = await client.get(f"/api/tables/teams/data?limit=5&filters={filters}")
    assert r.status_code == 400


# 22. Grouped endpoint — valid column
@pytest.mark.asyncio
async def test_grouped(client):
    r = await client.get("/api/tables/teams/grouped?group_by=conference_name")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "value" in data[0]
    assert "count" in data[0]


# 23. Grouped endpoint — invalid column rejected
@pytest.mark.asyncio
async def test_grouped_invalid_column(client):
    r = await client.get("/api/tables/teams/grouped?group_by=DROP+TABLE+teams")
    assert r.status_code == 400


# 24. Grouped endpoint — invalid table
@pytest.mark.asyncio
async def test_grouped_invalid_table(client):
    r = await client.get("/api/tables/fake_table/grouped?group_by=id")
    assert r.status_code == 404


# 25. Schema includes data types for type-aware filtering
@pytest.mark.asyncio
async def test_schema_has_data_types(client):
    r = await client.get("/api/tables/teams/schema")
    assert r.status_code == 200
    cols = r.json()["columns"]
    types = {c["column_name"]: c["data_type"] for c in cols}
    assert types["team_id"] == "integer"
    assert types["team_name"] == "text"


# 26. Sort descending
@pytest.mark.asyncio
async def test_table_data_sort_desc(client):
    r = await client.get(
        "/api/tables/teams/data?limit=5&sort_by=team_name&sort_dir=desc"
    )
    assert r.status_code == 200
    d = r.json()
    names = [row["team_name"] for row in d["rows"]]
    assert names == sorted(names, reverse=True)


# 27. Numeric range filter
@pytest.mark.asyncio
async def test_numeric_range_filter(client):
    import json as _json

    filters = _json.dumps({"team_id": {"min": 1, "max": 10}})
    r = await client.get(f"/api/tables/teams/data?limit=100&filters={filters}")
    assert r.status_code == 200
    d = r.json()
    for row in d["rows"]:
        assert 1 <= row["team_id"] <= 10


# 28. NL query requires API key
@pytest.mark.asyncio
async def test_nl_query_requires_api_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = await client.post("/api/nl-query", json={"question": "top teams by wins"})
    assert r.status_code == 500
