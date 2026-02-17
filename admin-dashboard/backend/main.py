import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"

DATABASE_URLS = {
    "nhl_betting": "postgresql://connorrainey@localhost:5432/nhl_betting",
    "polymarket": "postgresql://connorrainey@localhost:5432/polymarket",
}
# Default DB for backwards compatibility
DATABASE_URL = DATABASE_URLS["nhl_betting"]

# Auto-populated on startup — no more hardcoded allowlist
ALLOWED_TABLES: set[str] = set()
# Maps table name -> database name (for multi-DB routing)
TABLE_DB_MAP: dict[str, str] = {}

DANGEROUS_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
READ_ONLY_START_PATTERN = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

pool: Optional[asyncpg.Pool] = None
pools: dict[str, asyncpg.Pool] = {}


async def _discover_tables():
    """Auto-discover all public tables from all configured databases."""
    global ALLOWED_TABLES, TABLE_DB_MAP
    ALLOWED_TABLES = set()
    TABLE_DB_MAP = {}
    for db_name, db_pool in pools.items():
        rows = await db_pool.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        for row in rows:
            tbl = row["tablename"]
            # If same table name in multiple DBs, first one wins
            if tbl not in TABLE_DB_MAP:
                ALLOWED_TABLES.add(tbl)
                TABLE_DB_MAP[tbl] = db_name


def _get_pool(table_name: str | None = None) -> asyncpg.Pool:
    """Get the right connection pool for a table (or default)."""
    if table_name and table_name in TABLE_DB_MAP:
        return pools[TABLE_DB_MAP[table_name]]
    return pool  # type: ignore[return-value]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    for db_name, db_url in DATABASE_URLS.items():
        pools[db_name] = await asyncpg.create_pool(db_url, min_size=2, max_size=5)
    pool = pools["nhl_betting"]  # default
    await _discover_tables()
    yield
    for p in pools.values():
        await p.close()


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
    results = []
    for tbl in sorted(ALLOWED_TABLES):
        db_name = TABLE_DB_MAP.get(tbl, "nhl_betting")
        tbl_pool = pools[db_name]
        count = await tbl_pool.fetchval(f'SELECT COUNT(*) FROM "{tbl}"')
        results.append({"name": tbl, "row_count": count, "database": db_name})
    return results


@app.get("/api/tables/{name}/schema")
async def table_schema(name: str):
    validate_table_name(name)
    p = _get_pool(name)
    rows = await p.fetch(
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
    p = _get_pool(name)
    rows = await p.fetch(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        """,
        name,
    )
    return {r["column_name"] for r in rows}


async def _get_column_types(name: str) -> dict[str, str]:
    """Return mapping of column_name -> data_type for a table."""
    p = _get_pool(name)
    rows = await p.fetch(
        """
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        """,
        name,
    )
    return {r["column_name"]: r["data_type"] for r in rows}


def _validate_column(col: str, valid_cols: set[str], param_name: str) -> str:
    if col not in valid_cols:
        raise HTTPException(400, f"Invalid {param_name}: '{col}'")
    return col


def _is_read_only_query(sql: str) -> bool:
    stripped = sql.strip()
    if not stripped:
        return False
    # Allow a trailing semicolon but reject multiple statements.
    without_trailing = stripped[:-1] if stripped.endswith(";") else stripped
    if ";" in without_trailing:
        return False
    if not READ_ONLY_START_PATTERN.match(without_trailing):
        return False
    if DANGEROUS_PATTERN.search(without_trailing):
        return False
    return True


NUMERIC_PG_TYPES = {"integer", "bigint", "smallint", "numeric", "real", "double precision"}
DATE_PG_TYPES = {"date", "timestamp without time zone", "timestamp with time zone"}

TEXT_OPERATORS = {"contains", "equals", "starts_with", "ends_with"}
NUMERIC_OPERATORS = {"eq", "ne", "gt", "lt", "gte", "lte", "between"}
DATE_OPERATORS = {"before", "after", "between"}


def _build_operator_filter(
    col: str, operator: str, value, col_type: str, params: list, param_idx: int
) -> tuple[list[str], int]:
    """Build WHERE clause parts for an operator-based filter. Returns (clauses, new_param_idx)."""
    clauses: list[str] = []

    if col_type in NUMERIC_PG_TYPES:
        if operator == "between":
            if not isinstance(value, list) or len(value) != 2:
                raise HTTPException(400, f"'between' operator requires [min, max] array for '{col}'")
            clauses.append(f'"{col}" >= ${param_idx}')
            params.append(value[0])
            param_idx += 1
            clauses.append(f'"{col}" <= ${param_idx}')
            params.append(value[1])
            param_idx += 1
        else:
            op_map = {"eq": "=", "ne": "!=", "gt": ">", "lt": "<", "gte": ">=", "lte": "<="}
            sql_op = op_map.get(operator)
            if not sql_op:
                raise HTTPException(400, f"Invalid numeric operator: '{operator}'")
            clauses.append(f'"{col}" {sql_op} ${param_idx}')
            params.append(value)
            param_idx += 1

    elif col_type in DATE_PG_TYPES:
        if operator == "between":
            if not isinstance(value, list) or len(value) != 2:
                raise HTTPException(400, f"'between' operator requires [min, max] array for '{col}'")
            clauses.append(f'"{col}" >= ${param_idx}')
            params.append(value[0])
            param_idx += 1
            clauses.append(f'"{col}" <= ${param_idx}')
            params.append(value[1])
            param_idx += 1
        elif operator == "before":
            clauses.append(f'"{col}" < ${param_idx}')
            params.append(value)
            param_idx += 1
        elif operator == "after":
            clauses.append(f'"{col}" > ${param_idx}')
            params.append(value)
            param_idx += 1
        else:
            raise HTTPException(400, f"Invalid date operator: '{operator}'")

    else:
        # Text operators
        if operator == "contains":
            clauses.append(f'CAST("{col}" AS TEXT) ILIKE ${param_idx}')
            params.append(f"%{value}%")
            param_idx += 1
        elif operator == "equals":
            clauses.append(f'CAST("{col}" AS TEXT) ILIKE ${param_idx}')
            params.append(str(value))
            param_idx += 1
        elif operator == "starts_with":
            clauses.append(f'CAST("{col}" AS TEXT) ILIKE ${param_idx}')
            params.append(f"{value}%")
            param_idx += 1
        elif operator == "ends_with":
            clauses.append(f'CAST("{col}" AS TEXT) ILIKE ${param_idx}')
            params.append(f"%{value}")
            param_idx += 1
        else:
            raise HTTPException(400, f"Invalid text operator: '{operator}'")

    return clauses, param_idx


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
    col_types = await _get_column_types(name)

    # Build WHERE clause from filters
    where_parts: list[str] = []
    params: list[object] = []
    param_idx = 1

    if filters:
        try:
            parsed = json.loads(filters)
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid filters JSON")

        # New format: array of {column, operator, value}
        if isinstance(parsed, list):
            for f in parsed:
                if not isinstance(f, dict) or "column" not in f or "operator" not in f:
                    raise HTTPException(400, "Each filter must have 'column' and 'operator'")
                col = f["column"]
                _validate_column(col, valid_cols, "filter column")
                operator = f["operator"]
                value = f.get("value", "")
                col_type = col_types.get(col, "text")
                clauses, param_idx = _build_operator_filter(col, operator, value, col_type, params, param_idx)
                where_parts.extend(clauses)

        # Legacy format: dict of {col: val} or {col: {min, max}}
        elif isinstance(parsed, dict):
            for col, val in parsed.items():
                _validate_column(col, valid_cols, "filter column")
                if isinstance(val, dict) and ("min" in val or "max" in val):
                    if "min" in val:
                        where_parts.append(f'"{col}" >= ${param_idx}')
                        params.append(val["min"])
                        param_idx += 1
                    if "max" in val:
                        where_parts.append(f'"{col}" <= ${param_idx}')
                        params.append(val["max"])
                        param_idx += 1
                else:
                    where_parts.append(f'CAST("{col}" AS TEXT) ILIKE ${param_idx}')
                    params.append(f"%{val}%")
                    param_idx += 1
        else:
            raise HTTPException(400, "Filters must be a JSON array or object")

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    # Validate and build ORDER BY
    order_sql = ""
    if sort_by:
        _validate_column(sort_by, valid_cols, "sort_by column")
        direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
        order_sql = f' ORDER BY "{sort_by}" {direction} NULLS LAST'

    # Total count (unfiltered)
    p = _get_pool(name)
    total = await p.fetchval(f'SELECT COUNT(*) FROM "{name}"')

    # Filtered count
    count_params = list(params)
    filtered_total = await p.fetchval(
        f'SELECT COUNT(*) FROM "{name}"{where_sql}', *count_params
    )

    # Data query
    data_sql = (
        f'SELECT * FROM "{name}"{where_sql}{order_sql}'
        f" LIMIT ${param_idx} OFFSET ${param_idx + 1}"
    )
    params.append(limit)
    params.append(offset)

    rows = await p.fetch(data_sql, *params)
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

    p = _get_pool(name)
    rows = await p.fetch(
        f'SELECT "{group_by}" AS value, COUNT(*) AS count'
        f' FROM "{name}" GROUP BY "{group_by}" ORDER BY count DESC'
    )
    return [{"value": r["value"], "count": r["count"]} for r in rows]


class QueryRequest(BaseModel):
    sql: str
    db: str = "nhl_betting"


@app.get("/api/databases")
async def list_databases():
    """List available databases."""
    return [{"name": name} for name in DATABASE_URLS]


@app.post("/api/query")
async def run_query(req: QueryRequest):
    sql = req.sql.strip()
    if not sql:
        raise HTTPException(400, "Empty query")
    if req.db not in pools:
        raise HTTPException(400, f"Unknown database: '{req.db}'")
    if not _is_read_only_query(sql):
        raise HTTPException(
            403, "Only read-only queries are allowed (SELECT, WITH, etc.)"
        )
    try:
        rows = await pools[req.db].fetch(sql)
    except Exception as e:
        raise HTTPException(400, str(e))
    columns = [str(k) for k in rows[0].keys()] if rows else []
    return {
        "columns": columns,
        "rows": [dict(r) for r in rows],
        "row_count": len(rows),
    }


class NLQueryRequest(BaseModel):
    question: str
    db: str = "nhl_betting"


TYPE_SHORT = {
    "integer": "int", "bigint": "bigint", "smallint": "int",
    "numeric": "num", "real": "float", "double precision": "float",
    "character varying": "varchar", "text": "text", "boolean": "bool",
    "date": "date", "timestamp with time zone": "timestamptz",
    "timestamp without time zone": "timestamp",
}


async def _get_db_schema_text(db_name: str | None = None) -> str:
    """Build a compact schema description for LLM context."""
    parts: list[str] = []
    for tbl in sorted(ALLOWED_TABLES):
        tbl_db = TABLE_DB_MAP.get(tbl, "nhl_betting")
        if db_name and tbl_db != db_name:
            continue
        p = pools[tbl_db]
        rows = await p.fetch(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = $1
            ORDER BY ordinal_position
            """,
            tbl,
        )
        if not rows:
            continue
        cols = ", ".join(
            f"{r['column_name']} {TYPE_SHORT.get(r['data_type'], r['data_type'])}"
            for r in rows
        )
        parts.append(f"{tbl}({cols})")
    return "\n".join(parts)


FALLBACK_MODELS = [
    "qwen/qwen3-coder:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-r1-0528:free",
]


async def _openrouter_chat(
    api_key: str, model: str, messages: list, max_tokens: int = 1024
) -> str:
    """Call OpenRouter chat completions with automatic retry on failure."""
    import httpx

    models_to_try = [model] + [m for m in FALLBACK_MODELS if m != model]

    for attempt_model in models_to_try:
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": attempt_model,
                        "max_tokens": max_tokens,
                        "messages": messages,
                    },
                )
                if r.status_code == 429:
                    continue  # Try next model
                r.raise_for_status()
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                if not content:
                    continue  # Empty response, try next

                text = content.strip()
                # Strip <think>...</think> blocks (reasoning models)
                text = re.sub(
                    r"<think>.*?</think>", "", text, flags=re.DOTALL
                ).strip()
                # Strip markdown fences
                if "```" in text:
                    lines = text.split("\n")
                    lines = [
                        line
                        for line in lines
                        if not line.strip().startswith("```")
                    ]
                    text = "\n".join(lines).strip()
                # Extract SQL: find first SELECT/WITH and take everything
                match = re.search(
                    r"((?:SELECT|WITH)\b.*)",
                    text,
                    re.IGNORECASE | re.DOTALL,
                )
                if match:
                    text = match.group(1).strip()
                # Strip trailing junk after semicolon
                semi = text.find(";")
                if semi > 0:
                    text = text[: semi + 1]
                if text:
                    return text
        except Exception:
            continue

    raise HTTPException(
        502,
        "All models failed to generate a response. "
        "Try again in a few seconds.",
    )


@app.post("/api/nl-query")
async def nl_query(req: NLQueryRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "Empty question")

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(500, "OPENROUTER_API_KEY not configured")

    if req.db not in pools:
        raise HTTPException(400, f"Unknown database: '{req.db}'")
    schema_text = await _get_db_schema_text(req.db)
    model = os.environ.get("NL_QUERY_MODEL", "openrouter/free")

    # Single-pass: generate SQL and execute it
    system_msg = f"""You convert natural language questions into PostgreSQL SELECT queries.
Output ONLY the SQL query. No explanation, no markdown, no commentary.
Always add LIMIT 500 unless the user specifies a limit.
Only use tables and columns from the schema below.

Schema:
{schema_text}"""

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": question},
    ]

    generated_sql = await _openrouter_chat(api_key, model, messages)

    # Safety check
    if not _is_read_only_query(generated_sql):
        raise HTTPException(403, "Generated query is not read-only")

    try:
        rows = await pools[req.db].fetch(generated_sql)
    except Exception as e:
        raise HTTPException(400, f"Query execution error: {e}")

    columns = [str(k) for k in rows[0].keys()] if rows else []
    row_dicts = [dict(r) for r in rows]

    return {
        "sql": generated_sql,
        "columns": columns,
        "rows": row_dicts,
        "row_count": len(row_dicts),
        "summary": None,
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
