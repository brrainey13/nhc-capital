import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app, pool as _pool
import asyncpg


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


# 13. Empty query
@pytest.mark.asyncio
async def test_empty_query(client):
    r = await client.post("/api/query", json={"sql": ""})
    assert r.status_code == 400


# 14. Invalid SQL
@pytest.mark.asyncio
async def test_invalid_sql(client):
    r = await client.post("/api/query", json={"sql": "SELEC FROM"})
    assert r.status_code == 400


# 15. Table data 404
@pytest.mark.asyncio
async def test_table_data_not_found(client):
    r = await client.get("/api/tables/fake_table/data")
    assert r.status_code == 404
