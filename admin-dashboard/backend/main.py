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

DATABASE_URL = "postgresql://connorrainey@localhost:5432/nhl_betting"

ALLOWED_TABLES = {
    "api_snapshots", "cook_county_appeals", "cook_county_assessments",
    "cook_county_properties", "cook_county_sales", "cook_county_tax_rates",
    "game_team_stats", "games", "goalie_advanced", "goalie_saves_by_strength",
    "goalie_starts", "goalie_stats", "injuries", "injuries_live",
    "kanban_events", "kanban_tasks", "lineup_absences",
    "live_game_snapshots", "model_runs", "period_scores",
    "player_stats", "players", "predictions", "saves_odds", "schedules",
    "sf_rentals", "standings", "teams",
}

DANGEROUS_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
READ_ONLY_START_PATTERN = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

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


async def _get_column_types(name: str) -> dict[str, str]:
    """Return mapping of column_name -> data_type for a table."""
    rows = await pool.fetch(
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
    if not _is_read_only_query(sql):
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


class NLQueryRequest(BaseModel):
    question: str


TYPE_SHORT = {
    "integer": "int", "bigint": "bigint", "smallint": "int",
    "numeric": "num", "real": "float", "double precision": "float",
    "character varying": "varchar", "text": "text", "boolean": "bool",
    "date": "date", "timestamp with time zone": "timestamptz",
    "timestamp without time zone": "timestamp",
}


async def _get_db_schema_text() -> str:
    """Build a compact schema description for LLM context."""
    parts: list[str] = []
    for tbl in sorted(ALLOWED_TABLES):
        rows = await pool.fetch(
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

    schema_text = await _get_db_schema_text()
    model = os.environ.get("NL_QUERY_MODEL", "openrouter/free")

    # ── Pass 1: Generate SQL ──
    system_msg = f"""You convert questions into PostgreSQL SELECT queries.
Output ONLY the SQL. No explanation, no markdown.

Schema:
{schema_text}"""

    few_shot = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": "show all teams"},
        {"role": "assistant", "content": 'SELECT * FROM teams LIMIT 500;'},
        {"role": "user", "content": "top 5 goalies by saves"},
        {
            "role": "assistant",
            "content": (
                "SELECT player_id, SUM(saves) AS total_saves "
                "FROM goalie_stats GROUP BY player_id "
                "ORDER BY total_saves DESC LIMIT 5;"
            ),
        },
        {"role": "user", "content": "how many games per team"},
        {
            "role": "assistant",
            "content": (
                "SELECT home_team_id AS team_id, COUNT(*) AS games "
                "FROM games GROUP BY home_team_id "
                "ORDER BY games DESC LIMIT 500;"
            ),
        },
        {"role": "user", "content": question},
    ]

    generated_sql = await _openrouter_chat(api_key, model, few_shot)

    # Safety check
    if not _is_read_only_query(generated_sql):
        raise HTTPException(403, "Generated query is not read-only")

    try:
        rows = await pool.fetch(generated_sql)
    except Exception as e:
        raise HTTPException(400, f"Query execution error: {e}")

    columns = [str(k) for k in rows[0].keys()] if rows else []
    row_dicts = [dict(r) for r in rows]
    row_count = len(row_dicts)

    # ── Pass 2: Summarize results ──
    # Build a compact preview of the data (first 20 rows) for the summary model
    preview_rows = row_dicts[:20]
    preview_text = json.dumps(preview_rows, default=str, indent=None)[:3000]

    summary_prompt = f"""You are a data analyst. The user asked: "{question}"

This SQL was run:
{generated_sql}

It returned {row_count} rows with columns: {', '.join(columns)}.

Here is a preview of the data (up to 20 rows):
{preview_text}

Write a clear, concise summary (2-4 sentences) that:
1. Directly answers the user's question
2. Highlights key findings, patterns, or notable values
3. Mentions the total row count if relevant

Be specific — use actual numbers and names from the data. No SQL explanation needed."""

    try:
        summary = await _openrouter_chat(
            api_key, model, [{"role": "user", "content": summary_prompt}], max_tokens=512
        )
    except Exception:
        summary = None  # Non-fatal — we still have the data

    return {
        "sql": generated_sql,
        "columns": columns,
        "rows": row_dicts,
        "row_count": row_count,
        "summary": summary,
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
