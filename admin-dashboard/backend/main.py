import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import asyncpg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"

DATABASE_URL = "postgresql://connorrainey@localhost:5432/nhl_betting"

ALLOWED_TABLES = {
    "api_snapshots", "cook_county_appeals", "cook_county_assessments",
    "cook_county_properties", "cook_county_sales", "cook_county_tax_rates",
    "game_team_stats", "games", "goalie_stats", "injuries", "kanban_events",
    "kanban_tasks", "live_game_snapshots", "model_runs", "period_scores",
    "player_stats", "players", "predictions", "schedules", "sf_rentals",
    "standings", "teams",
}

DANGEROUS_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

pool: Optional[asyncpg.Pool] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    yield
    await pool.close()


app = FastAPI(title="NHC Admin Dashboard API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def validate_table_name(name: str) -> str:
    if name not in ALLOWED_TABLES:
        raise HTTPException(404, f"Table '{name}' not found")
    return name


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/tables")
async def list_tables():
    rows = await pool.fetch(
        """
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
        """
    )
    results = []
    for row in rows:
        name = row["tablename"]
        if name not in ALLOWED_TABLES:
            continue
        count = await pool.fetchval(f'SELECT COUNT(*) FROM "{name}"')
        results.append({"name": name, "row_count": count})
    return results


@app.get("/api/tables/{name}/schema")
async def table_schema(name: str):
    validate_table_name(name)
    rows = await pool.fetch(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        ORDER BY ordinal_position
        """,
        name,
    )
    return {
        "table": name,
        "columns": [dict(r) for r in rows],
    }


@app.get("/api/tables/{name}/data")
async def table_data(
    name: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    validate_table_name(name)
    rows = await pool.fetch(f'SELECT * FROM "{name}" LIMIT $1 OFFSET $2', limit, offset)
    total = await pool.fetchval(f'SELECT COUNT(*) FROM "{name}"')
    columns = [str(k) for k in rows[0].keys()] if rows else []
    return {
        "table": name,
        "columns": columns,
        "rows": [dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


class QueryRequest(BaseModel):
    sql: str


@app.post("/api/query")
async def run_query(req: QueryRequest):
    sql = req.sql.strip()
    if not sql:
        raise HTTPException(400, "Empty query")
    if DANGEROUS_PATTERN.search(sql):
        raise HTTPException(
            403, "Only read-only queries are allowed (SELECT, WITH, etc.)"
        )
    try:
        rows = await pool.fetch(sql)
    except Exception as e:
        raise HTTPException(400, str(e))
    columns = [str(k) for k in rows[0].keys()] if rows else []
    return {
        "columns": columns,
        "rows": [dict(r) for r in rows],
        "row_count": len(rows),
    }


# Serve frontend static files
if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        return FileResponse(FRONTEND_DIR / "index.html")
