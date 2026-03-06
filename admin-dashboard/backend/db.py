"""Database connection management — pool creation, table discovery, routing."""

import os

import asyncpg

DB_HOST = os.environ.get("DATABASE_HOST", "localhost")
DB_PORT = os.environ.get("DATABASE_PORT", "5432")
# Dashboard uses a read-only Postgres role — cannot INSERT/UPDATE/DELETE/DROP.
# This is defense-in-depth alongside the SQL validator in query.py.
DB_USER = os.environ.get("DASHBOARD_DB_USER", "dashboard_readonly")
DB_PASS = os.environ.get("DASHBOARD_DB_PASS", "")

def _db_url(dbname: str) -> str:
    auth = f"{DB_USER}:{DB_PASS}" if DB_PASS else DB_USER
    return f"postgresql://{auth}@{DB_HOST}:{DB_PORT}/{dbname}"


DATABASE_URLS = {
    "nhl_betting": _db_url("nhl_betting"),
    "polymarket": _db_url("polymarket"),
    "real_estate": _db_url("real_estate"),
}

# Auto-populated on startup — no hardcoded allowlist
ALLOWED_TABLES: set[str] = set()
TABLE_DB_MAP: dict[str, str] = {}

pools: dict[str, asyncpg.Pool] = {}
default_pool: asyncpg.Pool | None = None


async def init_pools():
    """Create connection pools for all databases and discover tables."""
    global default_pool
    for db_name, db_url in DATABASE_URLS.items():
        pools[db_name] = await asyncpg.create_pool(db_url, min_size=2, max_size=5)
    default_pool = pools["nhl_betting"]
    await _discover_tables()


async def close_pools():
    """Close all connection pools."""
    for p in pools.values():
        await p.close()


async def _discover_tables():
    """Auto-discover all public tables from all configured databases."""
    ALLOWED_TABLES.clear()
    TABLE_DB_MAP.clear()
    for db_name, db_pool in pools.items():
        rows = await db_pool.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        for row in rows:
            tbl = row["tablename"]
            if tbl not in TABLE_DB_MAP:
                ALLOWED_TABLES.add(tbl)
                TABLE_DB_MAP[tbl] = db_name


def get_pool(table_name: str | None = None) -> asyncpg.Pool:
    """Get the right connection pool for a table (or default)."""
    if table_name and table_name in TABLE_DB_MAP:
        return pools[TABLE_DB_MAP[table_name]]
    assert default_pool is not None, "Pools not initialized"
    return default_pool


async def get_table_columns(name: str) -> set[str]:
    """Return set of column names for a table."""
    p = get_pool(name)
    rows = await p.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1",
        name,
    )
    return {r["column_name"] for r in rows}


async def get_column_types(name: str) -> dict[str, str]:
    """Return mapping of column_name -> data_type for a table."""
    p = get_pool(name)
    rows = await p.fetch(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1",
        name,
    )
    return {r["column_name"]: r["data_type"] for r in rows}
