"""Data ingestion routes — POST endpoints for scrapers to push data.

These endpoints use the nhc_etl database role (INSERT/UPDATE only).
Configure via ETL_DB_USER and ETL_DB_PASS environment variables.
"""

import os

import asyncpg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

_etl_pools: dict[str, asyncpg.Pool] = {}

ETL_USER = os.environ.get("ETL_DB_USER", "nhc_etl")
ETL_PASS = os.environ.get("ETL_DB_PASS", "")
ETL_HOST = os.environ.get("DATABASE_HOST", "localhost")
ETL_PORT = os.environ.get("DATABASE_PORT", "5432")


def _etl_url(dbname: str) -> str:
    auth = f"{ETL_USER}:{ETL_PASS}" if ETL_PASS else ETL_USER
    return f"postgresql://{auth}@{ETL_HOST}:{ETL_PORT}/{dbname}"


async def _get_etl_pool(db: str) -> asyncpg.Pool:
    if db not in _etl_pools:
        _etl_pools[db] = await asyncpg.create_pool(_etl_url(db), min_size=1, max_size=3)
    return _etl_pools[db]


# ── Generic row insert ───────────────────────────────────────────────────────


class IngestRequest(BaseModel):
    """Push rows into a table. Columns are inferred from the first row."""

    db: str = "nhl_betting"
    table: str
    rows: list[dict]
    on_conflict: str | None = None  # e.g. "(id) DO NOTHING"


ALLOWED_INGEST_TABLES = {
    "nhl_betting": {
        "odds_snapshots",
        "game_results",
        "injuries",
        "goalie_advanced",
    },
    "polymarket": {
        "markets",
        "market_snapshots",
        "crypto_bars",
    },
    "real_estate": {
        "data_refresh_log",
    },
}


@router.post("/rows")
async def ingest_rows(req: IngestRequest):
    """Insert rows into an allowed table via the ETL role."""
    allowed = ALLOWED_INGEST_TABLES.get(req.db, set())
    if req.table not in allowed:
        raise HTTPException(
            403,
            f"Table '{req.table}' not in ingest allowlist for db '{req.db}'. "
            f"Allowed: {sorted(allowed)}",
        )
    if not req.rows:
        return {"inserted": 0}

    cols = list(req.rows[0].keys())
    placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
    col_names = ", ".join(cols)
    conflict = f" ON CONFLICT {req.on_conflict}" if req.on_conflict else ""
    sql = f"INSERT INTO {req.table} ({col_names}) VALUES ({placeholders}){conflict}"

    pool = await _get_etl_pool(req.db)
    async with pool.acquire() as conn:
        count = 0
        for row in req.rows:
            vals = [row.get(c) for c in cols]
            await conn.execute(sql, *vals)
            count += 1

    return {"inserted": count, "table": req.table, "db": req.db}


@router.get("/tables")
async def list_ingest_tables():
    """List tables available for data ingestion."""
    return ALLOWED_INGEST_TABLES
