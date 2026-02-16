import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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
    "player_stats", "players", "predictions", "saves_odds", "schedules",
    "sf_rentals", "standings", "teams",
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
ALLOWED_ORIGINS = [
    "https://alexzander-tightfisted-ambagiously.ngrok-free.dev",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",  # vite dev
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
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


async def _get_table_columns(name: str) -> set[str]:
    """Return set of column names for a validated table."""
    rows = await pool.fetch(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        """,
        name,
    )
    return {r["column_name"] for r in rows}


def _validate_column(col: str, valid_cols: set[str], param_name: str) -> str:
    if col not in valid_cols:
        raise HTTPException(400, f"Invalid {param_name}: '{col}'")
    return col


@app.get("/api/tables/{name}/data")
async def table_data(
    name: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    filters: str | None = Query(None),
):
    validate_table_name(name)
    valid_cols = await _get_table_columns(name)

    # Build WHERE clause from filters
    where_parts: list[str] = []
    params: list[object] = []
    param_idx = 1

    if filters:
        try:
            filter_dict = json.loads(filters)
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid filters JSON")
        for col, val in filter_dict.items():
            _validate_column(col, valid_cols, "filter column")
            if isinstance(val, dict) and ("min" in val or "max" in val):
                # Numeric range filter
                if "min" in val:
                    where_parts.append(f'"{col}" >= ${param_idx}')
                    params.append(val["min"])
                    param_idx += 1
                if "max" in val:
                    where_parts.append(f'"{col}" <= ${param_idx}')
                    params.append(val["max"])
                    param_idx += 1
            else:
                # Text ILIKE filter
                where_parts.append(f'CAST("{col}" AS TEXT) ILIKE ${param_idx}')
                params.append(f"%{val}%")
                param_idx += 1

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    # Validate and build ORDER BY
    order_sql = ""
    if sort_by:
        _validate_column(sort_by, valid_cols, "sort_by column")
        direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
        order_sql = f' ORDER BY "{sort_by}" {direction} NULLS LAST'

    # Total count (unfiltered)
    total = await pool.fetchval(f'SELECT COUNT(*) FROM "{name}"')

    # Filtered count
    count_params = list(params)
    filtered_total = await pool.fetchval(
        f'SELECT COUNT(*) FROM "{name}"{where_sql}', *count_params
    )

    # Data query
    data_sql = (
        f'SELECT * FROM "{name}"{where_sql}{order_sql}'
        f" LIMIT ${param_idx} OFFSET ${param_idx + 1}"
    )
    params.append(limit)
    params.append(offset)

    rows = await pool.fetch(data_sql, *params)
    columns = [str(k) for k in rows[0].keys()] if rows else []
    return {
        "table": name,
        "columns": columns,
        "rows": [dict(r) for r in rows],
        "total": total,
        "filtered_total": filtered_total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/tables/{name}/grouped")
async def table_grouped(
    name: str,
    group_by: str = Query(...),
):
    validate_table_name(name)
    valid_cols = await _get_table_columns(name)
    _validate_column(group_by, valid_cols, "group_by column")

    rows = await pool.fetch(
        f'SELECT "{group_by}" AS value, COUNT(*) AS count'
        f' FROM "{name}" GROUP BY "{group_by}" ORDER BY count DESC'
    )
    return [{"value": r["value"], "count": r["count"]} for r in rows]


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


SESSIONS_FILE = Path.home() / ".openclaw/agents/main/sessions/sessions.json"


@app.get("/api/usage")
async def usage():
    if not SESSIONS_FILE.exists():
        return {"sessions": [], "totals": {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0}}
    data = json.loads(SESSIONS_FILE.read_text())
    sessions = []
    total_tok = 0
    total_in = 0
    total_out = 0
    for key, s in data.items():
        label = s.get("displayName") or s.get("origin", {}).get("label", key)
        t_tokens = s.get("totalTokens", 0)
        i_tokens = s.get("inputTokens", 0)
        o_tokens = s.get("outputTokens", 0)
        ctx = s.get("contextTokens", 0)
        updated_ms = s.get("updatedAt", 0)
        updated = (
            datetime.fromtimestamp(updated_ms / 1000, tz=timezone.utc).isoformat()
            if updated_ms
            else None
        )
        sessions.append({
            "key": key,
            "label": label,
            "total_tokens": t_tokens,
            "input_tokens": i_tokens,
            "output_tokens": o_tokens,
            "context_window": ctx,
            "model": s.get("model", ""),
            "updated_at": updated,
        })
        total_tok += t_tokens
        total_in += i_tokens
        total_out += o_tokens
    sessions.sort(key=lambda x: x["total_tokens"], reverse=True)
    return {
        "sessions": sessions,
        "totals": {
            "total_tokens": total_tok,
            "input_tokens": total_in,
            "output_tokens": total_out,
        },
    }


# Serve frontend static files
if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        return FileResponse(FRONTEND_DIR / "index.html")
